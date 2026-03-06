require('dotenv').config()

const { app, BrowserWindow, ipcMain, desktopCapturer, dialog } = require('electron')
const { spawn, execSync } = require('child_process')
const path = require('path')
const fs = require('fs')
const os = require('os')

const API_BASE = 'http://localhost:8000'

let pythonProcess = null
let isQuitting = false

// Returns path to the bundled PyInstaller binary, or null in dev mode
function getPythonBinaryPath() {
  if (!app.isPackaged) return null
  const bin = process.platform === 'win32' ? 'mayihear-api.exe' : 'mayihear-api'
  return path.join(process.resourcesPath, 'mayihear-api', bin)
}

// Kills any process occupying port 8000 (stale from a previous crash)
function killStaleProcess() {
  try {
    if (process.platform === 'win32') {
      const out = execSync('netstat -ano -p TCP 2>nul', { encoding: 'utf-8' })
      const match = out.split('\n').find(l => l.includes(':8000') && l.includes('LISTENING'))
      if (match) {
        const pid = match.trim().split(/\s+/).pop()
        execSync(`taskkill /F /PID ${pid} /T 2>nul`)
        console.log(`[MayiHear] Killed stale process on port 8000 (PID ${pid})`)
      }
    } else {
      execSync("lsof -ti tcp:8000 | xargs -r kill -9")
      console.log('[MayiHear] Killed stale process on port 8000')
    }
  } catch (_) {
    // No stale process — normal path
  }
}

// Polls GET /health every 500 ms up to 15 s; returns true when API is ready
async function waitForApi() {
  const deadline = Date.now() + 15000
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${API_BASE}/health`)
      if (res.ok) return true
    } catch (_) {
      // Not ready yet
    }
    await new Promise(r => setTimeout(r, 500))
  }
  return false
}

// Spawns the bundled Python binary; no-op in dev mode
function startPythonApi() {
  const binPath = getPythonBinaryPath()
  if (!binPath) {
    console.log('[MayiHear] Dev mode — start the Python API manually: uvicorn api.main:app --port 8000')
    return
  }

  killStaleProcess()

  const dataDir = app.getPath('userData')
  console.log(`[MayiHear] Starting API binary: ${binPath}`)

  pythonProcess = spawn(binPath, [], {
    env: { ...process.env, MAYIHEAR_DATA_DIR: dataDir },
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: false,
  })

  pythonProcess.stdout.on('data', d => console.log('[API]', d.toString().trimEnd()))
  pythonProcess.stderr.on('data', d => console.error('[API]', d.toString().trimEnd()))
  pythonProcess.on('exit', (code, signal) => {
    console.log(`[MayiHear] API process exited (code=${code} signal=${signal})`)
    pythonProcess = null
    if (!isQuitting) {
      console.log('[MayiHear] API crashed unexpectedly — restarting in 2s...')
      setTimeout(startPythonApi, 2000)
    }
  })
}

// Terminates the Python API process
function stopPythonApi() {
  if (!pythonProcess) return
  const pid = pythonProcess.pid
  console.log(`[MayiHear] Stopping API (PID ${pid})...`)
  try {
    if (process.platform === 'win32') {
      execSync(`taskkill /F /PID ${pid} /T 2>nul`)
    } else {
      pythonProcess.kill('SIGTERM')
      setTimeout(() => {
        if (pythonProcess) pythonProcess.kill('SIGKILL')
      }, 3000)
    }
  } catch (err) {
    console.error('[MayiHear] Error stopping API:', err.message)
  }
  pythonProcess = null
}

function createWindow() {
  const win = new BrowserWindow({
    width: 960,
    height: 760,
    minWidth: 720,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    },
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#0f1117'
  })

  win.loadFile('renderer/index.html')
}

app.whenReady().then(async () => {
  startPythonApi()
  if (app.isPackaged) {
    const ready = await waitForApi()
    if (!ready) console.error('[MayiHear] API timeout — opening app anyway')
  }
  createWindow()
})

app.on('before-quit', () => { isQuitting = true; stopPythonApi() })

app.on('window-all-closed', () => {
  isQuitting = true
  stopPythonApi()
  if (process.platform !== 'darwin') app.quit()
})

// Returns available screen sources so renderer can pick one for audio capture
ipcMain.handle('get-sources', async () => {
  const sources = await desktopCapturer.getSources({ types: ['screen'] })
  return sources.map(s => ({ id: s.id, name: s.name }))
})

// Receives raw audio buffer, sends to Python API /transcription/transcribe
ipcMain.handle('transcribe-audio', async (_event, audioBuffer) => {
  const tmpPath = path.join(os.tmpdir(), `mayihear-${Date.now()}.webm`)
  const fileSizeMB = (audioBuffer.byteLength / 1024 / 1024).toFixed(1)
  console.log(`[MayiHear] transcribe-audio: ${fileSizeMB} MB — writing temp file...`)

  try {
    fs.writeFileSync(tmpPath, Buffer.from(audioBuffer))

    const fileBuffer = fs.readFileSync(tmpPath)
    const blob = new Blob([fileBuffer], { type: 'audio/webm' })
    const formData = new FormData()
    formData.append('file', blob, 'audio.webm')

    // 60-minute timeout — 50-minute recordings can take 25-35 min on Gemini
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 60 * 60 * 1000)

    console.log(`[MayiHear] Sending ${fileSizeMB} MB to transcription API...`)
    const t0 = Date.now()

    let response
    try {
      response = await fetch(`${API_BASE}/transcription/transcribe`, {
        method: 'POST',
        body: formData,
        signal: controller.signal
      })
    } catch (fetchErr) {
      const isAbort = fetchErr.name === 'AbortError' || fetchErr.cause?.name === 'AbortError'
      if (isAbort) {
        return { ok: false, error: `Transcription timed out after 60 minutes (file: ${fileSizeMB} MB). The recording may be too long for a single request.` }
      }
      throw fetchErr
    } finally {
      clearTimeout(timeoutId)
    }

    console.log(`[MayiHear] API responded in ${((Date.now() - t0) / 1000).toFixed(1)}s`)

    if (!response.ok) {
      const error = await response.text()
      return { ok: false, error: `Transcription API error: ${error}` }
    }

    const data = await response.json()
    console.log('[MayiHear] Transcript:', data.text?.slice(0, 200) || '(empty)')
    return { ok: true, text: data.text }

  } catch (err) {
    return {
      ok: false,
      error: `Could not reach Python API.\nMake sure it is running:\n\n  cd mayihear-api\n  uvicorn api.main:app --port 8000\n\nError: ${err.message}`
    }
  } finally {
    if (fs.existsSync(tmpPath)) fs.unlinkSync(tmpPath)
  }
})

// Saves transcript text to a .txt file via save dialog
ipcMain.handle('save-transcript', async (_event, text) => {
  const { filePath, canceled } = await dialog.showSaveDialog({
    title: 'Guardar transcripción',
    defaultPath: `transcripcion_${Date.now()}.txt`,
    filters: [{ name: 'Text file', extensions: ['txt'] }]
  })
  if (canceled || !filePath) return { saved: false }
  fs.writeFileSync(filePath, text, 'utf-8')
  return { saved: true, filePath }
})

// Sends transcript + context to Python API /insights/generate
ipcMain.handle('generate-insights', async (_event, transcript, context) => {
  try {
    const response = await fetch(`${API_BASE}/insights/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, user_context: context })
    })

    if (!response.ok) {
      const error = await response.text()
      return { ok: false, error: `Insights API error: ${error}` }
    }

    const data = await response.json()
    console.log('[MayiHear] Insights raw:', JSON.stringify(data, null, 2))
    const text = formatInsights(data)
    console.log('[MayiHear] Insights formatted:', text || '(empty — all fields were empty lists)')
    return { ok: true, text, raw: data }

  } catch (err) {
    return {
      ok: false,
      error: `Could not reach Python API.\nMake sure it is running:\n\n  cd mayihear-api\n  uvicorn api.main:app --port 8000\n\nError: ${err.message}`
    }
  }
})

// Sends transcript + context to Python API /meeting-act/generate
ipcMain.handle('generate-meeting-act', async (_event, transcript, context) => {
  try {
    const response = await fetch(`${API_BASE}/meeting-act/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, user_context: context })
    })

    if (!response.ok) {
      const error = await response.text()
      return { ok: false, error: `Meeting Act API error: ${error}` }
    }

    const data = await response.json()
    console.log('[MayiHear] Meeting Act raw:', JSON.stringify(data, null, 2))
    return { ok: true, data }

  } catch (err) {
    return {
      ok: false,
      error: `No se pudo conectar con la API Python.\nAsegúrate de que esté corriendo:\n\n  cd mayihear-api\n  uvicorn api.main:app --port 8000\n\nError: ${err.message}`
    }
  }
})

// Receives MeetingActResult, fetches .docx from API, saves via dialog
ipcMain.handle('download-word', async (_event, actaData) => {
  try {
    const response = await fetch(`${API_BASE}/meeting-act/word`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(actaData)
    })

    if (!response.ok) {
      const error = await response.text()
      return { ok: false, error: `Word API error: ${error}` }
    }

    const arrayBuffer = await response.arrayBuffer()
    const buffer = Buffer.from(arrayBuffer)

    const defaultName = actaData.fecha
      ? `acta_${actaData.fecha.replace(/\//g, '-')}.docx`
      : 'acta.docx'

    const { filePath, canceled } = await dialog.showSaveDialog({
      title: 'Guardar Acta de Reunión',
      defaultPath: defaultName,
      filters: [{ name: 'Word Document', extensions: ['docx'] }]
    })

    if (canceled || !filePath) {
      return { ok: true, saved: false }
    }

    fs.writeFileSync(filePath, buffer)
    console.log(`[MayiHear] Acta guardada en: ${filePath}`)
    return { ok: true, saved: true, filePath }

  } catch (err) {
    return { ok: false, error: err.message }
  }
})

// ── Monday.com IPC handlers ────────────────────────────────────

ipcMain.handle('monday-get-boards', async () => {
  try {
    const resp = await fetch(`${API_BASE}/monday/boards`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) {
    return { ok: false, error: err.message }
  }
})

ipcMain.handle('monday-get-items', async (_event, boardId) => {
  try {
    const resp = await fetch(`${API_BASE}/monday/boards/${boardId}/items`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) {
    return { ok: false, error: err.message }
  }
})

ipcMain.handle('monday-get-columns', async (_event, boardId) => {
  try {
    const resp = await fetch(`${API_BASE}/monday/boards/${boardId}/columns`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) {
    return { ok: false, error: err.message }
  }
})

ipcMain.handle('monday-publish', async (_event, boardId, itemId, columnId, actaData) => {
  try {
    const content = formatActaForMonday(actaData)
    const body = { board_id: boardId, item_id: itemId, content }
    if (columnId) body.column_id = columnId

    const resp = await fetch(`${API_BASE}/monday/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true }
  } catch (err) {
    return { ok: false, error: err.message }
  }
})

function formatActaForMonday(actaData) {
  const lines = []
  const name = actaData.nombre_reunion || 'Reunion'
  const date = actaData.fecha || new Date().toLocaleDateString('es-PE')

  lines.push(`${name} | ${date}`)
  lines.push('')

  if (actaData.resumen_ejecutivo) {
    lines.push('RESUMEN EJECUTIVO')
    lines.push(actaData.resumen_ejecutivo)
    lines.push('')
  }

  if (actaData.temas?.length) {
    lines.push('TEMAS TRATADOS')
    actaData.temas.forEach(t => {
      lines.push(`- ${t.titulo}`)
      if (t.avances?.length) t.avances.forEach(a => lines.push(`  Avance: ${a}`))
      if (t.bloqueantes?.length) t.bloqueantes.forEach(b => lines.push(`  Bloqueante: ${b}`))
    })
    lines.push('')
  }

  if (actaData.acuerdos?.length) {
    lines.push('ACUERDOS Y COMPROMISOS')
    actaData.acuerdos.forEach(a => {
      lines.push(a.responsable ? `- ${a.responsable}: ${a.accion}` : `- ${a.accion}`)
    })
    lines.push('')
  }

  if (actaData.riesgos?.length) {
    lines.push('RIESGOS')
    actaData.riesgos.forEach(r => lines.push(`- ${r}`))
    lines.push('')
  }

  if (actaData.proxima_reunion) {
    lines.push(`Proxima reunion: ${actaData.proxima_reunion}`)
  }

  return lines.join('\n').trim()
}

// Formats the structured InsightsResult into readable text
function formatInsights(data) {
  const lines = []

  if (data.summary?.length) {
    lines.push('## Summary')
    data.summary.forEach(s => lines.push(`• ${s}`))
    lines.push('')
  }

  if (data.decisions?.length) {
    lines.push('## Decisions Made')
    data.decisions.forEach(d => lines.push(`• ${d}`))
    lines.push('')
  }

  if (data.action_items?.length) {
    lines.push('## Action Items')
    data.action_items.forEach(a => {
      lines.push(a.person ? `• ${a.person} — ${a.task}` : `• ${a.task}`)
    })
    lines.push('')
  }

  if (data.open_questions?.length) {
    lines.push('## Open Questions')
    data.open_questions.forEach(q => lines.push(`• ${q}`))
  }

  const result = lines.join('\n').trim()

  if (!result) {
    return 'No structured insights could be extracted — the recording may be too short or contain no meeting content.\n\nRaw transcript was sent to the API successfully.'
  }

  return result
}
