// ── Elements ──────────────────────────────────────────────────
const recordBtn           = document.getElementById('record-btn')
const statusText          = document.getElementById('status-text')
const statusDot           = document.getElementById('status-dot')
const timerEl             = document.getElementById('timer')
const contextInput        = document.getElementById('context-input')
const transcriptSection   = document.getElementById('transcript-section')
const transcriptBox       = document.getElementById('transcript-box')
const insightsSection     = document.getElementById('insights-section')
const insightsBox         = document.getElementById('insights-box')
const copyTranscript      = document.getElementById('copy-transcript')
const saveTranscript      = document.getElementById('save-transcript')
const copyInsights        = document.getElementById('copy-insights')
const regenerateBtn       = document.getElementById('regenerate-btn')
const actaActions         = document.getElementById('acta-actions')
const generateActaBtn     = document.getElementById('generate-acta-btn')
const actaSection         = document.getElementById('acta-section')
const actaBox             = document.getElementById('acta-box')
const downloadActaBtn     = document.getElementById('download-acta')
const toggleMic           = document.getElementById('toggle-mic')
const toggleSystem        = document.getElementById('toggle-system')
const barMic              = document.getElementById('bar-mic')
const barSystem           = document.getElementById('bar-system')
const projectPreSelect    = document.getElementById('project-pre-select')
const mondaySection       = document.getElementById('monday-section')
const mondayProjectSelect = document.getElementById('monday-project-select')
const mondayPublishBtn    = document.getElementById('monday-publish-btn')
const mondayStatusText    = document.getElementById('monday-status-text')
const importTextarea      = document.getElementById('import-textarea')
const loadTxtBtn          = document.getElementById('load-txt-btn')
const clearImportBtn      = document.getElementById('clear-import-btn')
const generateFromTextBtn = document.getElementById('generate-from-text-btn')

// ── State ──────────────────────────────────────────────────────
let mediaRecorder     = null
let audioChunks       = []
let timerInterval     = null
let secondsElapsed    = 0
let isRecording       = false
let audioContext      = null
let lastTranscript    = ''
let currentActaData   = null

// Level meter animation state
let micAnalyser       = null
let systemAnalyser    = null
let micAnimFrame      = null
let systemAnimFrame   = null
let previewContext     = null  // AudioContext for live meter preview (not recording)

// ── Timer helpers ──────────────────────────────────────────────
function formatTime(s) {
  const m = String(Math.floor(s / 60)).padStart(2, '0')
  const sec = String(s % 60).padStart(2, '0')
  return `${m}:${sec}`
}

function startTimer() {
  secondsElapsed = 0
  timerEl.textContent = '00:00'
  timerEl.classList.add('visible')
  timerInterval = setInterval(() => {
    secondsElapsed++
    timerEl.textContent = formatTime(secondsElapsed)
  }, 1000)
}

function stopTimer() {
  clearInterval(timerInterval)
  timerEl.classList.remove('visible')
}

// ── Set UI state ───────────────────────────────────────────────
function setStatus(text) {
  statusText.textContent = text
}

function setRecordingUI(active) {
  isRecording = active
  recordBtn.textContent = active ? '■' : '●'
  recordBtn.classList.toggle('recording', active)
  statusDot.classList.toggle('recording', active)
}

// ── Level meter helpers ────────────────────────────────────────
function animateMeter(analyser, barEl, frameRef) {
  const dataArray = new Uint8Array(analyser.frequencyBinCount)
  function draw() {
    frameRef.current = requestAnimationFrame(draw)
    analyser.getByteFrequencyData(dataArray)
    const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length
    const pct = Math.min(100, (avg / 128) * 100)
    barEl.style.width = pct + '%'
  }
  draw()
}

function stopMeter(frameRef, barEl) {
  if (frameRef.current) {
    cancelAnimationFrame(frameRef.current)
    frameRef.current = null
  }
  barEl.style.width = '0%'
}

// We use wrapper objects so we can pass by reference
const micFrameRef    = { current: null }
const systemFrameRef = { current: null }

// ── Live preview meters (independent of recording) ─────────────
async function startPreviewMeters() {
  if (previewContext) return  // already running

  try {
    previewContext = new AudioContext()

    if (toggleMic.checked) {
      const micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      const micSrc = previewContext.createMediaStreamSource(micStream)
      micAnalyser = previewContext.createAnalyser()
      micAnalyser.fftSize = 256
      micSrc.connect(micAnalyser)
      animateMeter(micAnalyser, barMic, micFrameRef)
    }

    if (toggleSystem.checked) {
      const sources = await window.electronAPI.getSources()
      const desktopStream = await navigator.mediaDevices.getUserMedia({
        audio: { mandatory: { chromeMediaSource: 'desktop', chromeMediaSourceId: sources[0].id } },
        video: { mandatory: { chromeMediaSource: 'desktop', chromeMediaSourceId: sources[0].id, maxWidth: 1, maxHeight: 1, maxFrameRate: 1 } }
      })
      desktopStream.getVideoTracks().forEach(t => t.stop())
      if (desktopStream.getAudioTracks().length > 0) {
        const sysSrc = previewContext.createMediaStreamSource(new MediaStream(desktopStream.getAudioTracks()))
        systemAnalyser = previewContext.createAnalyser()
        systemAnalyser.fftSize = 256
        sysSrc.connect(systemAnalyser)
        animateMeter(systemAnalyser, barSystem, systemFrameRef)
      }
    }
  } catch (err) {
    console.warn('[MayiHear] Preview meters could not start:', err.message)
  }
}

function stopPreviewMeters() {
  stopMeter(micFrameRef, barMic)
  stopMeter(systemFrameRef, barSystem)
  if (previewContext) {
    previewContext.close()
    previewContext = null
  }
  micAnalyser = null
  systemAnalyser = null
}

// Listen for chunked transcription progress from main process
window.electronAPI.onTranscribeProgress(({ chunks_done, total_chunks }) => {
  if (total_chunks > 0) {
    const msg = `Transcribiendo fragmento ${chunks_done} de ${total_chunks}...`
    setStatus(msg)
    transcriptBox.textContent = msg + '\nLa grabacion fue guardada como backup en recordings/.'
  }
})

// Load Monday.com projects on startup — retries until API is ready
async function loadProjectsWithRetry(attemptsLeft = 10) {
  const result = await window.electronAPI.mondayGetProjects()
  if (!result.ok) {
    if (attemptsLeft > 1) {
      setTimeout(() => loadProjectsWithRetry(attemptsLeft - 1), 1500)
    } else {
      projectPreSelect.innerHTML = '<option value="">Sin conexion — reinicia la app</option>'
    }
    return
  }
  projectPreSelect.innerHTML = '<option value="">Seleccionar proyecto...</option>'
  result.data.forEach(item => {
    const opt = document.createElement('option')
    opt.value = item.id
    opt.textContent = item.name
    projectPreSelect.appendChild(opt)
  })
}
loadProjectsWithRetry()

// Start preview meters on load
startPreviewMeters()

// Toggle mic
toggleMic.addEventListener('change', async () => {
  stopPreviewMeters()
  if (toggleMic.checked || toggleSystem.checked) {
    await startPreviewMeters()
  }
})

// Toggle system audio
toggleSystem.addEventListener('change', async () => {
  stopPreviewMeters()
  if (toggleMic.checked || toggleSystem.checked) {
    await startPreviewMeters()
  }
})

// ── Get mixed audio stream based on toggle state ───────────────
async function getMixedAudioStream() {
  const useMic    = toggleMic.checked
  const useSystem = toggleSystem.checked

  if (!useMic && !useSystem) {
    throw new Error('Activa al menos una fuente de audio (micrófono o audio del sistema).')
  }

  // Stop preview meters before recording takes over
  stopPreviewMeters()

  audioContext = new AudioContext()
  const destination = audioContext.createMediaStreamDestination()

  // ── System audio (loopback) ──────────────────────────────────
  if (useSystem) {
    const sources = await window.electronAPI.getSources()
    const screenSource = sources[0]

    const desktopStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: 'desktop',
          chromeMediaSourceId: screenSource.id
        }
      },
      video: {
        mandatory: {
          chromeMediaSource: 'desktop',
          chromeMediaSourceId: screenSource.id,
          maxWidth: 1,
          maxHeight: 1,
          maxFrameRate: 1
        }
      }
    })
    desktopStream.getVideoTracks().forEach(t => t.stop())

    const systemTracks = desktopStream.getAudioTracks()
    console.log(`[MayiHear] Audio del sistema: ${systemTracks.length} pista(s)`)

    if (systemTracks.length === 0) {
      throw new Error('No se capturó audio del sistema. Activa "Mezcla estéreo" en Configuración de sonido de Windows → pestaña Grabación.')
    }

    // Attach live meter for system during recording
    systemAnalyser = audioContext.createAnalyser()
    systemAnalyser.fftSize = 256
    const sysSrc = audioContext.createMediaStreamSource(new MediaStream(systemTracks))
    sysSrc.connect(systemAnalyser)
    sysSrc.connect(destination)
    animateMeter(systemAnalyser, barSystem, systemFrameRef)
  }

  // ── Microphone ───────────────────────────────────────────────
  if (useMic) {
    try {
      const micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      console.log(`[MayiHear] Micrófono: ${micStream.getAudioTracks()[0]?.label}`)

      micAnalyser = audioContext.createAnalyser()
      micAnalyser.fftSize = 256
      const micSrc = audioContext.createMediaStreamSource(micStream)
      micSrc.connect(micAnalyser)
      micSrc.connect(destination)
      animateMeter(micAnalyser, barMic, micFrameRef)
    } catch (err) {
      console.warn('[MayiHear] Micrófono no disponible — grabando solo audio del sistema:', err.message)
      setStatus('Grabando (solo audio del sistema — micrófono no disponible)...')
    }
  }

  const sources_desc = [useSystem ? 'sistema' : null, useMic ? 'micrófono' : null].filter(Boolean).join(' + ')
  console.log(`[MayiHear] Stream mezclado listo — fuentes: ${sources_desc}`)
  return destination.stream
}

// ── Start recording ────────────────────────────────────────────
async function startRecording() {
  setStatus('Iniciando captura...')

  let stream
  try {
    stream = await getMixedAudioStream()
  } catch (err) {
    setStatus(`No se pudo acceder al audio: ${err.message}`)
    console.error(err)
    // Restart preview meters after failed attempt
    startPreviewMeters()
    return
  }

  audioChunks = []
  mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })

  mediaRecorder.ondataavailable = e => {
    if (e.data.size > 0) audioChunks.push(e.data)
  }

  mediaRecorder.onstop = handleRecordingStop

  mediaRecorder.start(1000)
  setRecordingUI(true)
  startTimer()
  setStatus('Grabando...')

  hideOutputs()
}

// ── Stop recording ─────────────────────────────────────────────
function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
    mediaRecorder.stream.getTracks().forEach(t => t.stop())
  }
  stopMeter(micFrameRef, barMic)
  stopMeter(systemFrameRef, barSystem)
  if (audioContext) {
    audioContext.close()
    audioContext = null
  }
  stopTimer()
  setRecordingUI(false)
  setStatus('Procesando...')
}

// ── After recording stops — transcribe then get insights ───────
async function handleRecordingStop() {
  const blob = new Blob(audioChunks, { type: 'audio/webm;codecs=opus' })
  const fileSizeMB = (blob.size / 1024 / 1024).toFixed(1)
  const durationMin = Math.round(secondsElapsed / 60)
  console.log(`[MayiHear] Audio blob: ${fileSizeMB} MB, ${durationMin} min (${secondsElapsed}s)`)

  const arrayBuffer = await blob.arrayBuffer()

  // ── Transcripción ──
  let sizeWarning
  if (blob.size > 200 * 1024 * 1024)
    sizeWarning = ` — grabacion muy larga (${fileSizeMB} MB), puede tomar 60-90 min`
  else if (blob.size > 30 * 1024 * 1024)
    sizeWarning = ` — archivo grande (${fileSizeMB} MB), puede tomar 15-40 min`
  else
    sizeWarning = ` (${fileSizeMB} MB)`

  setStatus(`Transcribiendo${sizeWarning}...`)
  showPanel(transcriptSection)
  transcriptBox.textContent = `Transcribiendo audio (${durationMin} min, ${fileSizeMB} MB)...\nEsto puede tomar bastante tiempo para grabaciones largas. La grabacion fue guardada como backup en la carpeta recordings/.`
  transcriptBox.classList.add('loading')

  const transcribeResult = await window.electronAPI.transcribeAudio(arrayBuffer)

  if (!transcribeResult.ok) {
    transcriptBox.textContent = `Error: ${transcribeResult.error}`
    transcriptBox.classList.remove('loading')
    setStatus('Transcripción fallida.')
    startPreviewMeters()
    return
  }

  const transcript = transcribeResult.text
  if (transcribeResult.savedPath) {
    console.log(`[MayiHear] Audio backup: ${transcribeResult.savedPath}`)
  }
  console.log(`[MayiHear] Transcripción recibida (${transcript.length} chars):`, transcript || '(vacío)')

  if (!transcript.trim()) {
    transcriptBox.textContent = 'No se detectó voz. Asegúrate de que el audio se esté reproduciendo por los altavoces o auriculares durante la grabación.'
    transcriptBox.classList.remove('loading')
    setStatus('No se detectó voz.')
    startPreviewMeters()
    return
  }

  transcriptBox.textContent = transcript
  transcriptBox.classList.remove('loading')
  lastTranscript = transcript
  regenerateBtn.style.display = 'inline-block'

  await runInsights(transcript)

  // Restart preview meters after processing
  startPreviewMeters()
}

// ── Insights pipeline (reusable) ───────────────────────────────
async function runInsights(transcript) {
  // Reset downstream outputs
  insightsBox.textContent = ''
  actaBox.textContent = ''
  insightsSection.classList.remove('visible')
  actaSection.classList.remove('visible')
  mondaySection.style.display = 'none'
  mondayStatusText.textContent = ''
  currentActaData = null

  // Show acta button (always available once transcript exists)
  actaActions.style.display = 'flex'
  generateActaBtn.disabled = false
  generateActaBtn.textContent = 'Generar Acta de Reunión'

  // ── Insights ──
  setStatus('Generando insights...')
  showPanel(insightsSection)
  insightsBox.textContent = 'Analizando transcripción...'
  insightsBox.classList.add('loading')

  const context = contextInput.value.trim()
  const insightsResult = await window.electronAPI.generateInsights(transcript, context)

  if (!insightsResult.ok) {
    insightsBox.textContent = `Error: ${insightsResult.error}`
    insightsBox.classList.remove('loading')
    setStatus('Insights fallidos.')
    return
  }

  const insightsText = insightsResult.text?.trim()
  insightsBox.textContent = insightsText || 'Los insights devolvieron vacío. Revisa los logs del terminal para la respuesta cruda de la API.'
  insightsBox.classList.remove('loading')
  setStatus('Listo.')
}

// ── Acta de Reunión ────────────────────────────────────────────
generateActaBtn.addEventListener('click', async () => {
  if (!lastTranscript) return

  generateActaBtn.disabled = true
  generateActaBtn.textContent = 'Generando...'
  showPanel(actaSection)
  actaBox.textContent = 'Generando acta de reunión...'
  actaBox.classList.add('loading')
  setStatus('Generando acta...')

  const context = contextInput.value.trim()
  const result = await window.electronAPI.generateMeetingAct(lastTranscript, context)

  if (!result.ok) {
    actaBox.textContent = `Error: ${result.error}`
    actaBox.classList.remove('loading')
    setStatus('Error al generar acta.')
    generateActaBtn.disabled = false
    generateActaBtn.textContent = 'Generar Acta de Reunión'
    return
  }

  currentActaData = result.data
  actaBox.textContent = formatMeetingAct(result.data)
  actaBox.classList.remove('loading')
  setStatus('Acta generada.')
  generateActaBtn.disabled = false
  generateActaBtn.textContent = 'Regenerar Acta'

  showMondaySection()
})

downloadActaBtn.addEventListener('click', async () => {
  if (!currentActaData) return
  downloadActaBtn.textContent = 'Guardando...'
  downloadActaBtn.disabled = true
  const result = await window.electronAPI.downloadWord(currentActaData)
  if (!result.ok) {
    setStatus(`Error al guardar: ${result.error}`)
  } else if (result.saved) {
    setStatus('Acta guardada correctamente.')
  }
  downloadActaBtn.textContent = 'Descargar .docx'
  downloadActaBtn.disabled = false
})

function formatMeetingAct(data) {
  const lines = []

  lines.push(`ACTA DE REUNIÓN`)
  lines.push(`Reunión: ${data.nombre_reunion || '—'}`)
  lines.push(`Fecha: ${data.fecha || '—'}`)

  if (data.participantes?.length) {
    lines.push(`Participantes: ${data.participantes.join(', ')}`)
  }
  lines.push('')

  if (data.resumen_ejecutivo) {
    lines.push('RESUMEN EJECUTIVO')
    lines.push(data.resumen_ejecutivo)
    lines.push('')
  }

  if (data.temas?.length) {
    lines.push('TEMAS TRATADOS')
    data.temas.forEach((t, i) => {
      lines.push(`${i + 1}. ${t.titulo}`)
      if (t.avances?.length) {
        t.avances.forEach(a => lines.push(`  Avance: ${a}`))
      }
      if (t.bloqueantes?.length) {
        t.bloqueantes.forEach(b => lines.push(`  Bloqueante: ${b}`))
      }
      if (t.aprendizajes?.length) {
        t.aprendizajes.forEach(ap => lines.push(`  Aprendizaje: ${ap}`))
      }
    })
    lines.push('')
  }

  if (data.acuerdos?.length) {
    lines.push('ACUERDOS Y COMPROMISOS')
    data.acuerdos.forEach(a => {
      lines.push(a.responsable ? `• ${a.responsable}: ${a.accion}` : `• ${a.accion}`)
    })
    lines.push('')
  }

  if (data.riesgos?.length) {
    lines.push('RIESGOS IDENTIFICADOS')
    data.riesgos.forEach(r => lines.push(`• ${r}`))
    lines.push('')
  }

  if (data.pendientes_reunion_anterior?.length) {
    lines.push('PENDIENTES DE REUNIÓN ANTERIOR')
    data.pendientes_reunion_anterior.forEach(p => lines.push(`• ${p}`))
    lines.push('')
  }

  if (data.proxima_reunion) {
    lines.push(`PRÓXIMA REUNIÓN: ${data.proxima_reunion}`)
  }

  return lines.join('\n').trim()
}

// ── UI helpers ─────────────────────────────────────────────────
function showPanel(el) {
  el.classList.add('visible')
}

function hideOutputs() {
  transcriptSection.classList.remove('visible')
  insightsSection.classList.remove('visible')
  actaSection.classList.remove('visible')
  actaActions.style.display = 'none'
  transcriptBox.textContent = ''
  insightsBox.textContent = ''
  actaBox.textContent = ''
  lastTranscript = ''
  currentActaData = null
  mondaySection.style.display = 'none'
  mondayStatusText.textContent = ''
  regenerateBtn.style.display = 'none'
}

regenerateBtn.addEventListener('click', async () => {
  if (!lastTranscript) return
  regenerateBtn.disabled = true
  await runInsights(lastTranscript)
  regenerateBtn.disabled = false
})

// ── Monday.com ─────────────────────────────────────────────────
function showMondaySection() {
  mondaySection.style.display = 'flex'
  mondayStatusText.textContent = ''

  // Mirror options from the pre-selector (already loaded at startup)
  mondayProjectSelect.innerHTML = projectPreSelect.innerHTML
  mondayProjectSelect.value = projectPreSelect.value
  mondayPublishBtn.disabled = !mondayProjectSelect.value
}

mondayProjectSelect.addEventListener('change', () => {
  mondayPublishBtn.disabled = !mondayProjectSelect.value
  mondayStatusText.textContent = ''
  projectPreSelect.value = mondayProjectSelect.value
})

mondayPublishBtn.addEventListener('click', async () => {
  if (!currentActaData || !mondayProjectSelect.value) return
  mondayPublishBtn.disabled = true
  mondayPublishBtn.textContent = 'Publicando...'
  mondayStatusText.textContent = ''

  const result = await window.electronAPI.mondayPublishActa(mondayProjectSelect.value, currentActaData)

  mondayPublishBtn.disabled = false
  mondayPublishBtn.textContent = 'Publicar'

  if (!result.ok) {
    mondayStatusText.textContent = `Error: ${result.error}`
    mondayStatusText.classList.add('error')
    mondayStatusText.classList.remove('success')
  } else {
    mondayStatusText.textContent = 'Acta publicada en Monday.com correctamente.'
    mondayStatusText.classList.add('success')
    mondayStatusText.classList.remove('error')
  }
})

// ── Import transcription ────────────────────────────────────────
importTextarea.addEventListener('input', () => {
  const hasText = importTextarea.value.trim().length > 0
  generateFromTextBtn.disabled = !hasText
  clearImportBtn.style.display = hasText ? 'inline-block' : 'none'
})

loadTxtBtn.addEventListener('click', async () => {
  const result = await window.electronAPI.loadTranscriptFile()
  if (!result.ok) return
  importTextarea.value = result.text
  importTextarea.dispatchEvent(new Event('input'))
})

clearImportBtn.addEventListener('click', () => {
  importTextarea.value = ''
  importTextarea.dispatchEvent(new Event('input'))
})

generateFromTextBtn.addEventListener('click', async () => {
  const text = importTextarea.value.trim()
  if (!text) return

  generateFromTextBtn.disabled = true
  generateFromTextBtn.textContent = 'Generando...'

  // Show transcript panel with the imported text
  lastTranscript = text
  transcriptBox.textContent = text
  transcriptBox.classList.remove('loading')
  showPanel(transcriptSection)
  regenerateBtn.style.display = 'inline-block'

  await runInsights(text)
  startPreviewMeters()

  generateFromTextBtn.disabled = false
  generateFromTextBtn.textContent = 'Generar Insights desde texto'
})

// ── Record button toggle ───────────────────────────────────────
recordBtn.addEventListener('click', () => {
  if (!isRecording) {
    startRecording()
  } else {
    stopRecording()
  }
})

// ── Copy buttons ───────────────────────────────────────────────
copyTranscript.addEventListener('click', () => {
  navigator.clipboard.writeText(transcriptBox.textContent)
  copyTranscript.textContent = '¡Copiado!'
  setTimeout(() => { copyTranscript.textContent = 'Copiar' }, 1500)
})

saveTranscript.addEventListener('click', async () => {
  const text = transcriptBox.textContent
  if (!text) return
  const result = await window.electronAPI.saveTranscript(text)
  if (result.saved) {
    saveTranscript.textContent = '¡Guardado!'
    setTimeout(() => { saveTranscript.textContent = 'Guardar .txt' }, 2000)
  }
})

copyInsights.addEventListener('click', () => {
  navigator.clipboard.writeText(insightsBox.textContent)
  copyInsights.textContent = '¡Copiado!'
  setTimeout(() => { copyInsights.textContent = 'Copiar' }, 1500)
})
