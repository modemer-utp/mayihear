require('dotenv').config()

const { app, BrowserWindow, ipcMain, desktopCapturer, dialog, shell } = require('electron')
const { spawn, execSync } = require('child_process')
const path = require('path')
const fs = require('fs')

const API_BASE = 'http://localhost:47891'
let RECORDINGS_DIR = null   // set after app is ready
let mainWindow = null
let pythonProcess = null
let isQuitting = false

// ── Settings helpers ──────────────────────────────────────────
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

// ── Python API lifecycle ──────────────────────────────────────
function getPythonBinaryPath() {
  if (!app.isPackaged) return null
  const bin = process.platform === 'win32' ? 'mayihear-api.exe' : 'mayihear-api'
  return path.join(process.resourcesPath, 'mayihear-api', bin)
}

function killStaleProcess() {
  try {
    if (process.platform === 'win32') {
      const out = execSync('netstat -ano -p TCP 2>nul', { encoding: 'utf-8' })
      const match = out.split('\n').find(l => l.includes(':47891') && l.includes('LISTENING'))
      if (match) {
        const pid = match.trim().split(/\s+/).pop()
        execSync(`taskkill /F /PID ${pid} /T 2>nul`)
      }
    } else {
      execSync('lsof -ti tcp:47891 | xargs -r kill -9')
    }
  } catch (_) {}
}

async function waitForApi() {
  const deadline = Date.now() + 15000
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${API_BASE}/health`)
      if (res.ok) return true
    } catch (_) {}
    await new Promise(r => setTimeout(r, 500))
  }
  return false
}

function startPythonApi() {
  const binPath = getPythonBinaryPath()
  if (!binPath) {
    console.log('[MayiHear] Dev mode — start Python API: cd mayihear-api && uvicorn api.main:app --port 47891')
    return
  }
  killStaleProcess()
  const dataDir = app.getPath('userData')
  pythonProcess = spawn(binPath, [], {
    env: { ...process.env, MAYIHEAR_DATA_DIR: dataDir },
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: false,
  })
  pythonProcess.stdout.on('data', d => console.log('[API]', d.toString().trimEnd()))
  pythonProcess.stderr.on('data', d => console.error('[API]', d.toString().trimEnd()))
  pythonProcess.on('exit', (code) => {
    console.log(`[MayiHear] API exited (code=${code})`)
    pythonProcess = null
    if (!isQuitting) setTimeout(startPythonApi, 2000)
  })
}

function stopPythonApi() {
  if (!pythonProcess) return
  const pid = pythonProcess.pid
  try {
    if (process.platform === 'win32') {
      execSync(`taskkill /F /PID ${pid} /T 2>nul`)
    } else {
      pythonProcess.kill('SIGTERM')
      setTimeout(() => { if (pythonProcess) pythonProcess.kill('SIGKILL') }, 3000)
    }
  } catch (_) {}
  pythonProcess = null
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1060,
    height: 800,
    minWidth: 780,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    },
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#13151c'
  })
  mainWindow.loadFile('renderer/index.html')
  mainWindow.on('closed', () => { mainWindow = null })
}

async function pushSettingsToApi() {
  const s = loadSettings()
  const body = {}
  if (s.gemini_api_key)    body.gemini_api_key    = s.gemini_api_key
  if (s.monday_token)      body.monday_token      = s.monday_token
  if (s.monday_board_id)   body.monday_board_id   = s.monday_board_id
  if (s.monday_column_id)  body.monday_column_id  = s.monday_column_id
  if (s.transcription_mode) body.transcription_mode = s.transcription_mode
  if (s.whisper_model)      body.whisper_model      = s.whisper_model
  if (s.vertex_sa_path !== undefined) body.vertex_sa_path = s.vertex_sa_path || ''
  if (!Object.keys(body).length) return
  try {
    await fetch(`${API_BASE}/settings/api-keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
  } catch (_) {}
}

function getRecordingsDir() {
  const s = loadSettings()
  const dir = s.recordings_dir || path.join(app.getPath('userData'), 'recordings')
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
  return dir
}

app.whenReady().then(async () => {
  RECORDINGS_DIR = getRecordingsDir()

  startPythonApi()
  if (app.isPackaged) {
    const ready = await waitForApi()
    if (!ready) console.error('[MayiHear] API timeout — opening app anyway')
  }
  createWindow()
  setTimeout(pushSettingsToApi, 3000)
})

app.on('before-quit', () => { isQuitting = true; stopPythonApi() })
app.on('window-all-closed', () => {
  isQuitting = true
  stopPythonApi()
  if (process.platform !== 'darwin') app.quit()
})

// ── Background job polling ────────────────────────────────────
async function pollJobInBackground(job_id) {
  const deadline = Date.now() + 4 * 60 * 60 * 1000
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 4000))
    if (!mainWindow || mainWindow.isDestroyed()) break
    try {
      const resp = await fetch(`${API_BASE}/transcription/status/${job_id}`)
      if (!resp.ok) continue
      const status = await resp.json()
      mainWindow.webContents.send('job-update', { job_id, ...status })
      if (status.status === 'done' || status.status === 'error') break
    } catch (_) {}
  }
}

// ── IPC: Desktop capture ──────────────────────────────────────
ipcMain.handle('get-sources', async () => {
  const sources = await desktopCapturer.getSources({ types: ['screen'] })
  return sources.map(s => ({ id: s.id, name: s.name }))
})

// ── IPC: Transcription (non-blocking) ─────────────────────────
ipcMain.handle('transcribe-audio', async (_event, audioBuffer, profileId) => {
  const fileSizeMB = (audioBuffer.byteLength / 1024 / 1024).toFixed(1)
  try {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const savedPath = path.join(RECORDINGS_DIR, `recording_${timestamp}.webm`)
    fs.writeFileSync(savedPath, Buffer.from(audioBuffer))

    const startResp = await fetch(`${API_BASE}/transcription/transcribe-file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: savedPath, profile_id: profileId || null })
    })
    if (!startResp.ok) return { ok: false, error: await startResp.text() }
    const { job_id } = await startResp.json()

    pollJobInBackground(job_id)
    return { ok: true, job_id, savedPath, fileSizeMB }
  } catch (err) {
    return { ok: false, error: `No se pudo conectar con la API: ${err.message}` }
  }
})

ipcMain.handle('get-all-jobs', async () => {
  try {
    const resp = await fetch(`${API_BASE}/transcription/jobs`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('get-job-text', async (_event, job_id) => {
  try {
    const resp = await fetch(`${API_BASE}/transcription/job-text/${job_id}`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    const { text } = await resp.json()
    return { ok: true, text }
  } catch (err) { return { ok: false, error: err.message } }
})

// ── IPC: File system ──────────────────────────────────────────
ipcMain.handle('get-recordings-dir', () => ({ ok: true, path: RECORDINGS_DIR }))

ipcMain.handle('pick-recordings-dir', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Seleccionar carpeta de grabaciones',
    defaultPath: RECORDINGS_DIR,
    properties: ['openDirectory', 'createDirectory']
  })
  if (result.canceled || !result.filePaths.length) return { ok: false }
  const chosen = result.filePaths[0]
  if (!fs.existsSync(chosen)) fs.mkdirSync(chosen, { recursive: true })
  saveSettingsFile({ recordings_dir: chosen })
  RECORDINGS_DIR = chosen
  return { ok: true, path: chosen }
})

ipcMain.handle('pick-vertex-credentials', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Seleccionar credenciales de Vertex AI (service account JSON)',
    filters: [{ name: 'JSON', extensions: ['json'] }],
    properties: ['openFile']
  })
  if (result.canceled || !result.filePaths.length) return { ok: false }
  const chosen = result.filePaths[0]
  saveSettingsFile({ vertex_sa_path: chosen })
  await pushSettingsToApi()
  return { ok: true, path: chosen }
})

ipcMain.handle('clear-vertex-credentials', async () => {
  saveSettingsFile({ vertex_sa_path: '' })
  await pushSettingsToApi()
  return { ok: true }
})

ipcMain.handle('open-recordings-folder', async () => {
  await shell.openPath(RECORDINGS_DIR)
  return { ok: true }
})

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

ipcMain.handle('load-transcript-file', async () => {
  const { filePaths, canceled } = await dialog.showOpenDialog({
    title: 'Cargar transcripción',
    filters: [{ name: 'Text file', extensions: ['txt'] }],
    properties: ['openFile']
  })
  if (canceled || !filePaths?.length) return { ok: false }
  const text = fs.readFileSync(filePaths[0], 'utf-8')
  return { ok: true, text }
})

// ── IPC: AI processing ────────────────────────────────────────
ipcMain.handle('generate-insights', async (_event, transcript, context, jobId) => {
  try {
    // Return stored insights immediately if available
    if (jobId) {
      const stored = await fetch(`${API_BASE}/insights/stored/${jobId}`)
      if (stored.ok) {
        const { text } = await stored.json()
        if (text) return { ok: true, text, cached: true }
      }
    }

    const response = await fetch(`${API_BASE}/insights/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, user_context: context })
    })
    if (!response.ok) return { ok: false, error: await response.text() }
    const data = await response.json()
    const text = formatInsights(data)

    // Persist for next time
    if (jobId && text) {
      fetch(`${API_BASE}/insights/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, insights_text: text })
      }).catch(() => {})
    }

    return { ok: true, text, raw: data }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('generate-meeting-act', async (_event, transcript, context, actaTemplate) => {
  try {
    const response = await fetch(`${API_BASE}/meeting-act/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, user_context: context, acta_template: actaTemplate || '' })
    })
    if (!response.ok) return { ok: false, error: await response.text() }
    return { ok: true, data: await response.json() }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('download-word', async (_event, actaData) => {
  try {
    const response = await fetch(`${API_BASE}/meeting-act/word`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(actaData)
    })
    if (!response.ok) return { ok: false, error: await response.text() }
    const buffer = Buffer.from(await response.arrayBuffer())
    const defaultName = actaData.fecha ? `acta_${actaData.fecha.replace(/\//g, '-')}.docx` : 'acta.docx'
    const { filePath, canceled } = await dialog.showSaveDialog({
      title: 'Guardar Acta de Reunión',
      defaultPath: defaultName,
      filters: [{ name: 'Word Document', extensions: ['docx'] }]
    })
    if (canceled || !filePath) return { ok: true, saved: false }
    fs.writeFileSync(filePath, buffer)
    return { ok: true, saved: true, filePath }
  } catch (err) { return { ok: false, error: err.message } }
})

// ── IPC: Chat ────────────────────────────────────────────────
ipcMain.handle('chat-message', async (_event, transcript, history, message) => {
  try {
    const response = await fetch(`${API_BASE}/chat/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, history, message })
    })
    if (!response.ok) return { ok: false, error: await response.text() }
    const data = await response.json()
    return { ok: true, response: data.response }
  } catch (err) { return { ok: false, error: err.message } }
})

// ── IPC: Monday.com ───────────────────────────────────────────
ipcMain.handle('monday-get-projects', async () => {
  try {
    const resp = await fetch(`${API_BASE}/monday/projects`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('monday-publish-acta', async (_event, itemId, actaData) => {
  try {
    const resp = await fetch(`${API_BASE}/monday/publish-acta`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, content: formatActaForMonday(actaData) })
    })
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('monday-get-boards', async () => {
  try {
    const resp = await fetch(`${API_BASE}/monday/boards`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('monday-get-items', async (_event, boardId) => {
  try {
    const resp = await fetch(`${API_BASE}/monday/boards/${boardId}/items`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('monday-get-columns', async (_event, boardId) => {
  try {
    const resp = await fetch(`${API_BASE}/monday/boards/${boardId}/columns`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('monday-publish', async (_event, boardId, itemId, columnId, actaData) => {
  try {
    const body = { board_id: boardId, item_id: itemId, content: formatActaForMonday(actaData) }
    if (columnId) body.column_id = columnId
    const resp = await fetch(`${API_BASE}/monday/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('monday-board-details', async (_event, boardId) => {
  try {
    const resp = await fetch(`${API_BASE}/monday/boards/${boardId}/details`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('monday-test-connection', async () => {
  try {
    const resp = await fetch(`${API_BASE}/monday/boards`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    const boards = await resp.json()
    return { ok: true, boards_count: boards.length }
  } catch (err) { return { ok: false, error: err.message } }
})

// ── IPC: Shell ────────────────────────────────────────────────
ipcMain.handle('open-external', (_e, url) => shell.openExternal(url))

// ── IPC: Settings ─────────────────────────────────────────────
ipcMain.handle('get-settings', () => {
  const s = loadSettings()
  const mask = v => v?.length >= 8 ? `...${v.slice(-4)}` : (v ? '••••' : '')
  return {
    ...s,
    gemini_api_key: '',
    gemini_configured: !!s.gemini_api_key,
    gemini_hint: mask(s.gemini_api_key),
    monday_token: '',
    monday_configured: !!s.monday_token,
    monday_hint: mask(s.monday_token),
    monday_board_id: s.monday_board_id || '',
    monday_column_id: s.monday_column_id || '',
    monday_auto_publish: !!s.monday_auto_publish,
    transcription_mode: s.transcription_mode || 'gemini',
    whisper_model: s.whisper_model || 'small',
    vertex_sa_path: s.vertex_sa_path || '',
    vertex_configured: !!s.vertex_sa_path,
  }
})

ipcMain.handle('save-settings', async (_event, data) => {
  saveSettingsFile(data)
  await pushSettingsToApi()
  return { ok: true }
})

ipcMain.handle('settings-status', async () => {
  try {
    const resp = await fetch(`${API_BASE}/settings/status`)
    if (!resp.ok) return { ok: false }
    return { ok: true, ...(await resp.json()) }
  } catch (_) { return { ok: false } }
})

// ── IPC: Profiles ─────────────────────────────────────────────
ipcMain.handle('get-profiles', async () => {
  try {
    const resp = await fetch(`${API_BASE}/profiles`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, data: await resp.json() }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('save-profile', async (_event, profile) => {
  try {
    const resp = await fetch(`${API_BASE}/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profile)
    })
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, ...(await resp.json()) }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('delete-profile', async (_event, profileId) => {
  try {
    const resp = await fetch(`${API_BASE}/profiles/${profileId}`, { method: 'DELETE' })
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('export-profiles', async () => {
  try {
    const resp = await fetch(`${API_BASE}/profiles/export`)
    if (!resp.ok) return { ok: false, error: await resp.text() }
    const profiles = await resp.json()
    const { filePath, canceled } = await dialog.showSaveDialog(mainWindow, {
      title: 'Exportar perfiles',
      defaultPath: `mayihear_profiles_${Date.now()}.json`,
      filters: [{ name: 'JSON', extensions: ['json'] }]
    })
    if (canceled || !filePath) return { ok: true, saved: false }
    fs.writeFileSync(filePath, JSON.stringify(profiles, null, 2), 'utf-8')
    return { ok: true, saved: true, filePath }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('import-profiles', async () => {
  try {
    const { filePaths, canceled } = await dialog.showOpenDialog(mainWindow, {
      title: 'Importar perfiles',
      filters: [{ name: 'JSON', extensions: ['json'] }],
      properties: ['openFile']
    })
    if (canceled || !filePaths?.length) return { ok: false, canceled: true }
    const raw = JSON.parse(fs.readFileSync(filePaths[0], 'utf-8'))
    const profiles = Array.isArray(raw) ? raw : [raw]
    const resp = await fetch(`${API_BASE}/profiles/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profiles)
    })
    if (!resp.ok) return { ok: false, error: await resp.text() }
    return { ok: true, ...(await resp.json()) }
  } catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('set-default-profile', (_event, profileId) => {
  saveSettingsFile({ default_profile_id: profileId || null })
  return { ok: true }
})

// ── Format helpers ────────────────────────────────────────────
function formatActaForMonday(d) {
  const lines = [`${d.nombre_reunion || 'Reunion'} | ${d.fecha || new Date().toLocaleDateString('es-PE')}`, '']
  if (d.resumen_ejecutivo) { lines.push('RESUMEN EJECUTIVO', d.resumen_ejecutivo, '') }
  if (d.temas?.length) {
    lines.push('TEMAS TRATADOS')
    d.temas.forEach(t => {
      lines.push(`- ${t.titulo}`)
      t.avances?.forEach(a => lines.push(`  Avance: ${a}`))
      t.bloqueantes?.forEach(b => lines.push(`  Bloqueante: ${b}`))
    })
    lines.push('')
  }
  if (d.acuerdos?.length) {
    lines.push('ACUERDOS Y COMPROMISOS')
    d.acuerdos.forEach(a => lines.push(a.responsable ? `- ${a.responsable}: ${a.accion}` : `- ${a.accion}`))
    lines.push('')
  }
  if (d.riesgos?.length) { lines.push('RIESGOS'); d.riesgos.forEach(r => lines.push(`- ${r}`)); lines.push('') }
  if (d.proxima_reunion) lines.push(`Proxima reunion: ${d.proxima_reunion}`)
  return lines.join('\n').trim()
}

function formatInsights(data) {
  const lines = []
  if (data.summary?.length)       { lines.push('## Resumen');           data.summary.forEach(s => lines.push(`• ${s}`));       lines.push('') }
  if (data.decisions?.length)     { lines.push('## Decisiones');        data.decisions.forEach(d => lines.push(`• ${d}`));      lines.push('') }
  if (data.action_items?.length)  { lines.push('## Acciones');          data.action_items.forEach(a => lines.push(a.person ? `• ${a.person} — ${a.task}` : `• ${a.task}`)); lines.push('') }
  if (data.open_questions?.length){ lines.push('## Preguntas abiertas'); data.open_questions.forEach(q => lines.push(`• ${q}`)) }
  return lines.join('\n').trim() || 'No se pudieron extraer insights — el audio puede ser muy corto o no contener reunión.'
}
