require('dotenv').config()

const { app, BrowserWindow, ipcMain, desktopCapturer } = require('electron')
const path = require('path')
const fs = require('fs')
const os = require('os')

const API_BASE = 'http://localhost:8000'

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

app.whenReady().then(createWindow)

app.on('window-all-closed', () => {
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

  try {
    fs.writeFileSync(tmpPath, Buffer.from(audioBuffer))

    const fileBuffer = fs.readFileSync(tmpPath)
    const blob = new Blob([fileBuffer], { type: 'audio/webm' })
    const formData = new FormData()
    formData.append('file', blob, 'audio.webm')

    const response = await fetch(`${API_BASE}/transcription/transcribe`, {
      method: 'POST',
      body: formData
    })

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
