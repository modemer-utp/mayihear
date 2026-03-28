require('dotenv').config()

const { app, BrowserWindow, ipcMain, desktopCapturer, dialog } = require('electron')
const { spawn, execSync } = require('child_process')
const path = require('path')
const fs = require('fs')
const os = require('os')

const API_BASE = 'http://localhost:8001'
const RECORDINGS_DIR = path.join(__dirname, 'recordings')
const SETTINGS_PATH = path.join(app.getPath ? app.getPath('userData') : __dirname, 'settings.json')

// ── Settings helpers ─────────────────────────────────────────
function getSettingsPath() {
  try { return path.join(app.getPath('userData'), 'settings.json') } catch (_) { return path.join(__dirname, 'settings.json') }
}

function loadSettings() {
  const p = getSettingsPath()
  try {
    if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, 'utf-8'))
  } catch (_) {}
  return { gemini_api_key: '', monday_token: '', monday_board_id: '', monday_column_id: '', monday_auto_publish: false }
}

function saveSettingsFile(data) {
  const merged = { ...loadSettings(), ...data }
  fs.writeFileSync(getSettingsPath(), JSON.stringify(merged, null, 2), 'utf-8')
  return merged
}

let pythonProcess = null
let isQuitting = false

// Ensure recordings folder exists
if (!fs.existsSync(RECORDINGS_DIR)) {
  fs.mkdirSync(RECORDINGS_DIR, { recursive: true })
  console.log(`[MayiHear] Created recordings folder: ${RECORDINGS_DIR}`)
}

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
      const match = out.split('\n').find(l => l.includes(':8001') && l.includes('LISTENING'))
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
    console.log('[MayiHear] Dev mode — start the Python API manually: uvicorn api.main:app --port 8001')
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

async function pushSettingsToApi() {
  const s = loadSettings()
  const body = {}
  if (s.gemini_api_key)   body.gemini_api_key   = s.gemini_api_key
  if (s.monday_token)     body.monday_token     = s.monday_token
  if (s.monday_board_id)  body.monday_board_id  = s.monday_board_id
  if (s.monday_column_id) body.monday_column_id = s.monday_column_id
  if (s.transcription_mode) body.transcription_mode = s.transcription_mode
  if (s.whisper_model)      body.whisper_model      = s.whisper_model
  if (Object.keys(body).length === 0) return
  try {
    await fetch(`${API_BASE}/settings/api-keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    console.log('[MayiHear] Settings pushed to API')
  } catch (_) {}
}

app.whenReady().then(async () => {
  startPythonApi()
  if (app.isPackaged) {
    const ready = await waitForApi()
    if (!ready) console.error('[MayiHear] API timeout — opening app anyway')
  }
  createWindow()
  // Push saved API keys to Python once ready (3s delay to let API start)
  setTimeout(pushSettingsToApi, 3000)
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

// Receives raw audio buffer, saves to recordings folder, starts chunked transcription job, polls for result
ipcMain.handle('transcribe-audio', async (event, audioBuffer) => {
  const fileSizeMB = (audioBuffer.byteLength / 1024 / 1024).toFixed(1)
  console.log(`[MayiHear] transcribe-audio: ${fileSizeMB} MB`)

  try {
    // Save to recordings folder
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const savedPath = path.join(RECORDINGS_DIR, `recording_${timestamp}.webm`)
    fs.writeFileSync(savedPath, Buffer.from(audioBuffer))
    console.log(`[MayiHear] Recording saved: ${savedPath} (${fileSizeMB} MB)`)

    // Start background transcription job — returns immediately with job_id
    const startResp = await fetch(`${API_BASE}/transcription/transcribe-file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: savedPath })
    })
    if (!startResp.ok) {
      const err = await startResp.text()
      return { ok: false, error: `Transcription API error: ${err}` }
    }
    const { job_id } = await startResp.json()
    console.log(`[MayiHear] Transcription job started: ${job_id}`)

    // Poll status every 5s, send progress updates to renderer
    const POLL_INTERVAL = 5000
    const MAX_WAIT_MS = 4 * 60 * 60 * 1000  // 4 hours max
    const deadline = Date.now() + MAX_WAIT_MS

    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, POLL_INTERVAL))

      let status
      try {
        const statusResp = await fetch(`${API_BASE}/transcription/status/${job_id}`)
        if (!statusResp.ok) {
          console.warn(`[MayiHear] Status poll failed: ${statusResp.status}`)
          continue
        }
        status = await statusResp.json()
      } catch (pollErr) {
        console.warn(`[MayiHear] Poll error (API down?): ${pollErr.message}`)
        continue
      }

      // Send progress to renderer
      event.sender.send('transcribe-progress', {
        chunks_done: status.chunks_done,
        total_chunks: status.total_chunks
      })

      if (status.status === 'done') {
        console.log(`[MayiHear] Job ${job_id} done — ${status.text?.length} chars`)
        return { ok: true, text: status.text, savedPath }
      }
      if (status.status === 'error') {
        return { ok: false, error: status.error || 'Transcription failed' }
      }
    }

    return { ok: false, error: `Transcription timed out after 4 hours. Recording saved at: ${savedPath}` }

  } catch (err) {
    return {
      ok: false,
      error: `Could not reach Python API.\nMake sure it is running:\n\n  cd mayihear-api\n  uvicorn api.main:app --port 8001\n\nError: ${err.message}`
    }
  }
})

// Returns the list of saved recordings in the recordings folder
ipcMain.handle('list-recordings', async () => {
  try {
    const files = fs.readdirSync(RECORDINGS_DIR)
      .filter(f => f.endsWith('.webm'))
      .map(f => ({ name: f, path: path.join(RECORDINGS_DIR, f) }))
      .sort((a, b) => b.name.localeCompare(a.name))
    return { ok: true, files }
  } catch (err) {
    return { ok: false, error: err.message }
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
      error: `Could not reach Python API.\nMake sure it is running:\n\n  cd mayihear-api\n  uvicorn api.main:app --port 8001\n\nError: ${err.message}`
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
      error: `No se pudo conectar con la API Python.\nAsegúrate de que esté corriendo:\n\n  cd mayihear-api\n  uvicorn api.main:app --port 8001\n\nError: ${err.message}`
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

ipcMain.handle('monday-get-projects', async () => {
  try {
    const resp = await fetch(`${API_BASE}/monday/projects`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) {
    return { ok: false, error: err.message }
  }
})

ipcMain.handle('monday-publish-acta', async (_event, itemId, actaData) => {
  try {
    const content = formatActaForMonday(actaData)
    const resp = await fetch(`${API_BASE}/monday/publish-acta`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, content })
    })
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true }
  } catch (err) {
    return { ok: false, error: err.message }
  }
})

ipcMain.handle('get-settings', () => {
  const s = loadSettings()
  // Return masked hints instead of raw keys for display
  const mask = v => v && v.length >= 8 ? `...${v.slice(-4)}` : (v ? '••••' : '')
  return {
    ...s,
    gemini_api_key: '',          // never send key back to renderer
    gemini_configured: !!s.gemini_api_key,
    gemini_hint: mask(s.gemini_api_key),
    monday_token: '',
    monday_configured: !!s.monday_token,
    monday_hint: mask(s.monday_token),
    monday_board_id: s.monday_board_id || '',
    monday_column_id: s.monday_column_id || '',
    monday_auto_publish: !!s.monday_auto_publish,
    transcription_mode: s.transcription_mode || 'gemini',
    whisper_model: s.whisper_model || 'small'
  }
})

ipcMain.handle('save-settings', async (_event, data) => {
  const settings = saveSettingsFile(data)
  await pushSettingsToApi()
  return { ok: true }
})

ipcMain.handle('monday-board-details', async (_event, boardId) => {
  try {
    const resp = await fetch(`${API_BASE}/monday/boards/${boardId}/details`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) {
    return { ok: false, error: err.message }
  }
})

ipcMain.handle('monday-test-connection', async () => {
  try {
    const resp = await fetch(`${API_BASE}/monday/boards`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    const boards = await resp.json()
    return { ok: true, boards_count: boards.length }
  } catch (err) {
    return { ok: false, error: err.message }
  }
})

ipcMain.handle('settings-status', async () => {
  try {
    const resp = await fetch(`${API_BASE}/settings/status`)
    if (!resp.ok) return { ok: false }
    return { ok: true, ...(await resp.json()) }
  } catch (_) {
    return { ok: false }
  }
})

ipcMain.handle('load-transcript-file', async () => {
  const { filePath, canceled } = await dialog.showOpenDialog({
    title: 'Cargar transcripcion',
    filters: [{ name: 'Text file', extensions: ['txt'] }],
    properties: ['openFile']
  })
  if (canceled || !filePath) return { ok: false }
  const text = fs.readFileSync(filePath[0], 'utf-8')
  return { ok: true, text }
})

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
