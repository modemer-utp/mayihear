// ── DOM refs ──────────────────────────────────────────────────────
const recordBtn          = document.getElementById('record-btn')
const statusText         = document.getElementById('status-text')
const timerEl            = document.getElementById('timer')
const apiDot             = document.getElementById('api-dot')
const toggleMic          = document.getElementById('toggle-mic')
const toggleSystem       = document.getElementById('toggle-system')
const barMic             = document.getElementById('bar-mic')
const barSystem          = document.getElementById('bar-system')
const recordingsPathText = document.getElementById('recordings-path-text')
const openFolderBtn      = document.getElementById('open-folder-btn')
const setupBanner        = document.getElementById('setup-banner')
const setupBannerBtn     = document.getElementById('setup-banner-btn')

const importToggleBtn     = document.getElementById('import-toggle-btn')
const importArea          = document.getElementById('import-area')
const importTextarea      = document.getElementById('import-textarea')
const loadTxtBtn          = document.getElementById('load-txt-btn')
const generateFromTextBtn = document.getElementById('generate-from-text-btn')
const cancelImportBtn     = document.getElementById('cancel-import-btn')

// Nav
const navRunningBadge    = document.getElementById('nav-running-badge')
const gotoRecordBtn      = document.getElementById('goto-record-btn')
const jobsList           = document.getElementById('jobs-list')
const jobsEmpty          = document.getElementById('jobs-empty')
const jobDetailEmpty     = document.getElementById('job-detail-empty')
const jobDetailContent   = document.getElementById('job-detail-content')

// Job detail refs
const jobProfileSelect      = document.getElementById('job-profile-select')
const regenerateInsightsBtn = document.getElementById('regenerate-insights-btn')
const transcriptBox         = document.getElementById('transcript-box')
const insightsBox           = document.getElementById('insights-box')
const saveTranscriptBtn     = document.getElementById('save-transcript')
const copyTranscriptBtn     = document.getElementById('copy-transcript')
const copyInsightsBtn       = document.getElementById('copy-insights')
const generateActaBtn       = document.getElementById('generate-acta-btn')
const regenerateActaBtn     = document.getElementById('regenerate-acta-btn')
const actaEmptyState        = document.getElementById('acta-empty-state')
const actaReadyState        = document.getElementById('acta-ready-state')
const actaBox               = document.getElementById('acta-box')
const actaModeBadge         = document.getElementById('acta-mode-badge')
const actaModeLabel         = document.getElementById('acta-mode-label')
const downloadActaBtn       = document.getElementById('download-acta')
const chatMessages          = document.getElementById('chat-messages')
const chatInput             = document.getElementById('chat-input')
const chatSendBtn           = document.getElementById('chat-send-btn')
const mondaySection         = document.getElementById('monday-section')
const mondayProjectSelect   = document.getElementById('monday-project-select')
const mondayPublishBtn      = document.getElementById('monday-publish-btn')
const mondayStatusText      = document.getElementById('monday-status-text')

// ── Profile DOM refs ──────────────────────────────────────────────
const recordProfileSelect    = document.getElementById('record-profile-select')
const profilesNewBtn         = document.getElementById('profiles-new-btn')
const profilesExportBtn      = document.getElementById('profiles-export-btn')
const profilesImportBtn      = document.getElementById('profiles-import-btn')
const profilesList           = document.getElementById('profiles-list')
const profilesEmpty          = document.getElementById('profiles-empty')
const profileDetailEmpty     = document.getElementById('profile-detail-empty')
const profileFormArea        = document.getElementById('profile-form-area')
const profileFormTitle       = document.getElementById('profile-form-title')
const pfStepIndicator        = document.getElementById('pf-step-indicator')
const pfTrack                = document.getElementById('pf-track')
const pfName                 = document.getElementById('pf-name')
const pfContext              = document.getElementById('pf-context')
const pfActaTemplate         = document.getElementById('pf-acta-template')
const pfCancelBtn            = document.getElementById('pf-cancel-btn')
const pfBackBtn              = document.getElementById('pf-back-btn')
const pfNextBtn              = document.getElementById('pf-next-btn')
const pfSaveBtn              = document.getElementById('pf-save-btn')
const sDefaultProfile        = document.getElementById('s-default-profile')
const sDefaultProfileSaveBtn = document.getElementById('s-default-profile-save-btn')
const sDefaultProfileStatus  = document.getElementById('s-default-profile-status')

// ── State ─────────────────────────────────────────────────────────
let isRecording       = false
let mediaRecorder     = null
let audioChunks       = []
let timerInterval     = null
let secondsElapsed    = 0
let audioContext      = null
let micGainNode       = null
let micAnalyser       = null
let systemAnalyser    = null
let previewContext    = null
const micFrameRef     = { current: null }
const systemFrameRef  = { current: null }

let jobs              = {}
let selectedJobId     = null
let lastTranscript    = ''
let currentActaData   = null
let appSettings       = {}
let mondayProjectsLoaded = false
let chatHistory       = []
const insightsCache   = {}   // job_id → insights text

let profiles          = []
let editingProfile    = null
let currentProfileStep = 1

// ── Page navigation ───────────────────────────────────────────────
const PAGE_MAP = { record: 'page-record', transcriptions: 'page-transcriptions', profiles: 'page-profiles' }
const PAGE_REVERSE = { 'page-record': 'record', 'page-transcriptions': 'transcriptions', 'page-profiles': 'profiles' }

function showPage(pageId) {
  document.querySelectorAll('.page').forEach(p => {
    p.classList.toggle('hidden', p.id !== pageId)
    p.classList.toggle('active', p.id === pageId)
  })
  document.querySelectorAll('.nav-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.page === (PAGE_REVERSE[pageId] || 'record'))
  })
}

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => showPage(PAGE_MAP[btn.dataset.page] || 'page-record'))
})

gotoRecordBtn.addEventListener('click', () => showPage('page-record'))

// ── Sub-tab switching (within job detail) ─────────────────────────
function switchSubTab(tab) {
  document.querySelectorAll('.sub-tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab)
  })
  document.querySelectorAll('.sub-tab-pane').forEach(p => {
    p.classList.toggle('hidden', p.id !== `tab-${tab}`)
    if (p.id === `tab-${tab}`) p.classList.remove('hidden')
  })
}

document.querySelectorAll('.sub-tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchSubTab(btn.dataset.tab))
})

// ── Init ──────────────────────────────────────────────────────────
async function init() {
  const dirResult = await window.electronAPI.getRecordingsDir()
  if (dirResult.ok) recordingsPathText.textContent = dirResult.path

  const s = await window.electronAPI.getSettings()
  appSettings = s
  if (!s.gemini_configured) setupBanner.classList.remove('hidden')

  await loadProfiles()
  await refreshJobList()

  Object.values(jobs).forEach(job => {
    if (job.status === 'running') pollJobInRenderer(job.id)
  })

  startPreviewMeters()
  apiDot.classList.add('ready')
}

// ── Job list management ───────────────────────────────────────────
async function refreshJobList() {
  const result = await window.electronAPI.getAllJobs()
  if (!result.ok) return
  jobs = {}
  result.data.forEach(j => { jobs[j.id] = j })
  renderJobSidebar()
}

function renderJobSidebar() {
  const jobArr = Object.values(jobs).sort((a, b) =>
    new Date(b.created_at) - new Date(a.created_at)
  )

  // Update running badge
  const runningCount = jobArr.filter(j => j.status === 'running').length
  navRunningBadge.textContent = runningCount
  navRunningBadge.classList.toggle('hidden', runningCount === 0)

  // Clear list (keep empty sentinel)
  Array.from(jobsList.querySelectorAll('.job-item')).forEach(el => el.remove())

  if (jobArr.length === 0) {
    jobsEmpty.style.display = 'block'
    return
  }

  jobsEmpty.style.display = 'none'
  jobArr.forEach(job => jobsList.appendChild(buildJobItem(job)))
}

function buildJobItem(job) {
  const el = document.createElement('div')
  el.className = 'job-item' + (job.id === selectedJobId ? ' selected' : '')
  el.dataset.jobId = job.id

  const dot = document.createElement('span')
  dot.className = `job-item-dot ${job.status}`

  const body = document.createElement('div')
  body.className = 'job-item-body'

  const name = document.createElement('div')
  name.className = 'job-item-name'
  name.textContent = job.file_name || `Grabación ${job.id}`

  const meta = document.createElement('div')
  meta.className = 'job-item-meta'
  meta.textContent = getJobStatusLabel(job) + (job.created_at ? ' · ' + formatRelativeTime(job.created_at) : '')

  body.appendChild(name)
  body.appendChild(meta)
  el.appendChild(dot)
  el.appendChild(body)

  el.addEventListener('click', () => {
    if (job.status === 'done') selectJob(job.id)
  })

  return el
}

function getJobStatusLabel(job) {
  if (job.status === 'running') {
    if (job.total_chunks > 0) return `${job.chunks_done}/${job.total_chunks} fragmentos`
    return 'Transcribiendo...'
  }
  if (job.status === 'done') return 'Listo'
  if (job.status === 'error') return 'Error'
  return job.status
}

function formatRelativeTime(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const diffMin = Math.floor((Date.now() - date) / 60000)
  if (diffMin < 1) return 'ahora'
  if (diffMin < 60) return `hace ${diffMin}m`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `hace ${diffH}h`
  return date.toLocaleDateString('es-PE', { day: '2-digit', month: '2-digit' })
}

// ── Job update listener ───────────────────────────────────────────
window.electronAPI.onJobUpdate(data => {
  const { job_id, ...fields } = data
  if (!jobs[job_id]) jobs[job_id] = { id: job_id }
  Object.assign(jobs[job_id], fields)
  renderJobSidebar()

  if (job_id === selectedJobId && fields.status === 'done') {
    loadTranscriptForJob(job_id)
  }
})

async function pollJobInRenderer(job_id) {
  while (true) {
    await new Promise(r => setTimeout(r, 5000))
    const result = await window.electronAPI.getAllJobs()
    if (!result.ok) continue
    const job = result.data.find(j => j.id === job_id)
    if (!job) break
    jobs[job_id] = job
    renderJobSidebar()
    if (job.status === 'done' || job.status === 'error') break
  }
}

// ── Select job ────────────────────────────────────────────────────
async function selectJob(job_id) {
  if (selectedJobId === job_id) return
  selectedJobId = job_id

  lastTranscript = ''
  currentActaData = null
  chatHistory = []
  transcriptBox.textContent = ''
  insightsBox.textContent = ''
  actaBox.textContent = ''
  actaEmptyState.classList.remove('hidden')
  actaReadyState.classList.add('hidden')
  mondaySection.classList.add('hidden')
  mondayStatusText.textContent = ''
  chatMessages.innerHTML = '<div class="chat-empty">Haz una pregunta sobre esta reunión para empezar.</div>'

  // Set profile selector from the job's associated profile (or default)
  const job = jobs[job_id]
  const profileId = job?.profile_id || appSettings.default_profile_id || ''
  jobProfileSelect.value = profiles.find(p => p.id === profileId) ? profileId : ''

  updateActaModeBadge()
  jobDetailEmpty.style.display = 'none'
  jobDetailContent.classList.remove('hidden')
  switchSubTab('transcript')
  renderJobSidebar()

  await loadTranscriptForJob(job_id)
}

async function loadTranscriptForJob(job_id) {
  transcriptBox.classList.add('loading')
  transcriptBox.textContent = 'Cargando transcripción...'
  insightsBox.textContent = ''
  insightsBox.classList.remove('loading')

  const result = await window.electronAPI.getJobText(job_id)
  if (!result.ok) {
    transcriptBox.textContent = `Error: ${result.error}`
    transcriptBox.classList.remove('loading')
    return
  }

  const transcript = result.text || ''
  transcriptBox.textContent = transcript
  transcriptBox.classList.remove('loading')
  lastTranscript = transcript

  generateActaBtn.disabled = false
  generateActaBtn.textContent = 'Generar Acta de Reunión'

  await runInsights(transcript)
}

// ── Active profile context helpers ───────────────────────────────
function getActiveProfile() {
  const id = jobProfileSelect.value
  return id ? profiles.find(p => p.id === id) : null
}

function getActiveContext() {
  return getActiveProfile()?.context_for_insights || ''
}

jobProfileSelect.addEventListener('change', () => {
  updateActaModeBadge()
  if (lastTranscript) runInsights(lastTranscript, true)
})

// ── Insights ──────────────────────────────────────────────────────
async function runInsights(transcript, forceRegenerate = false) {
  if (!transcript.trim()) {
    insightsBox.textContent = 'No se detectó texto en la transcripción.'
    return
  }

  if (transcript.trim().length < 300) {
    insightsBox.textContent = 'Grabación demasiado corta para generar insights.'
    return
  }

  if (!forceRegenerate && selectedJobId && insightsCache[selectedJobId]) {
    insightsBox.textContent = insightsCache[selectedJobId]
    return
  }

  insightsBox.classList.add('loading')
  insightsBox.textContent = 'Analizando transcripción con Gemini...'

  const context = getActiveContext()
  const result = await window.electronAPI.generateInsights(transcript, context, selectedJobId)

  insightsBox.classList.remove('loading')
  if (!result.ok) {
    insightsBox.textContent = `Error al generar insights: ${result.error}`
    return
  }

  const text = result.text || 'Sin insights.'
  insightsBox.textContent = text
  if (selectedJobId) insightsCache[selectedJobId] = text
}

regenerateInsightsBtn.addEventListener('click', async () => {
  if (!lastTranscript) return
  regenerateInsightsBtn.disabled = true
  await runInsights(lastTranscript, true)
  regenerateInsightsBtn.disabled = false
})

// ── Acta ──────────────────────────────────────────────────────────
function updateActaModeBadge() {
  const hasTemplate = !!(getActiveProfile()?.acta_template?.trim())
  const label = hasTemplate ? 'Plantilla personalizada' : 'Estructura inteligente'
  if (actaModeBadge) {
    actaModeBadge.textContent = label
    actaModeBadge.classList.toggle('freeform', hasTemplate)
  }
  if (actaModeLabel) actaModeLabel.textContent = label
}

async function doGenerateActa() {
  if (!lastTranscript) return
  generateActaBtn.disabled = true
  generateActaBtn.textContent = 'Generando...'
  actaEmptyState.classList.remove('hidden')
  actaReadyState.classList.add('hidden')
  actaBox.classList.add('loading')
  actaBox.textContent = 'Generando acta de reunión...'
  switchSubTab('acta')

  const context = getActiveContext()
  const actaTemplate = getActiveProfile()?.acta_template || ''
  const result = await window.electronAPI.generateMeetingAct(lastTranscript, context, actaTemplate)

  actaBox.classList.remove('loading')
  generateActaBtn.disabled = false
  generateActaBtn.textContent = 'Generar Acta de Reunión'

  if (!result.ok) {
    actaBox.textContent = `Error: ${result.error}`
    return
  }

  currentActaData = result.data
  actaBox.textContent = result.data.is_freeform
    ? (result.data.free_form_text || '')
    : formatMeetingAct(result.data)
  actaEmptyState.classList.add('hidden')
  actaReadyState.classList.remove('hidden')
  updateActaModeBadge()

  showMondaySection()
  if (appSettings.monday_auto_publish) autoPublish(result.data)
}

generateActaBtn.addEventListener('click', doGenerateActa)
regenerateActaBtn.addEventListener('click', doGenerateActa)

downloadActaBtn.addEventListener('click', async () => {
  if (!currentActaData) return
  downloadActaBtn.textContent = 'Guardando...'
  downloadActaBtn.disabled = true
  const result = await window.electronAPI.downloadWord(currentActaData)
  if (result.ok && result.saved) {
    downloadActaBtn.textContent = '¡Guardado!'
    setTimeout(() => { downloadActaBtn.textContent = 'Descargar .docx' }, 2000)
  } else {
    downloadActaBtn.textContent = 'Descargar .docx'
  }
  downloadActaBtn.disabled = false
})

function formatMeetingAct(data) {
  const lines = ['ACTA DE REUNIÓN', `Reunión: ${data.nombre_reunion || '—'}`, `Fecha: ${data.fecha || '—'}`]
  if (data.participantes?.length) lines.push(`Participantes: ${data.participantes.join(', ')}`)
  lines.push('')
  if (data.resumen_ejecutivo) { lines.push('RESUMEN EJECUTIVO', data.resumen_ejecutivo, '') }
  if (data.temas?.length) {
    lines.push('TEMAS TRATADOS')
    data.temas.forEach((t, i) => {
      lines.push(`${i + 1}. ${t.titulo}`)
      t.avances?.forEach(a => lines.push(`  Avance: ${a}`))
      t.bloqueantes?.forEach(b => lines.push(`  Bloqueante: ${b}`))
      t.aprendizajes?.forEach(ap => lines.push(`  Aprendizaje: ${ap}`))
    })
    lines.push('')
  }
  if (data.acuerdos?.length) {
    lines.push('ACUERDOS Y COMPROMISOS')
    data.acuerdos.forEach(a => lines.push(a.responsable ? `• ${a.responsable}: ${a.accion}` : `• ${a.accion}`))
    lines.push('')
  }
  if (data.riesgos?.length) {
    lines.push('RIESGOS IDENTIFICADOS')
    data.riesgos.forEach(r => lines.push(`• ${r}`))
    lines.push('')
  }
  if (data.pendientes_reunion_anterior?.length) {
    lines.push('PENDIENTES ANTERIOR')
    data.pendientes_reunion_anterior.forEach(p => lines.push(`• ${p}`))
    lines.push('')
  }
  if (data.proxima_reunion) lines.push(`PRÓXIMA REUNIÓN: ${data.proxima_reunion}`)
  return lines.join('\n').trim()
}

// ── Chat ──────────────────────────────────────────────────────────
function appendChatBubble(role, text, isLoading = false) {
  const empty = chatMessages.querySelector('.chat-empty')
  if (empty) empty.remove()

  const bubble = document.createElement('div')
  bubble.className = `chat-bubble ${role}`

  const label = document.createElement('div')
  label.className = 'chat-bubble-label'
  label.textContent = role === 'user' ? 'Tú' : 'IA'

  const textEl = document.createElement('div')
  textEl.className = 'chat-bubble-text' + (isLoading ? ' loading' : '')
  textEl.textContent = isLoading ? 'Pensando...' : text

  bubble.appendChild(label)
  bubble.appendChild(textEl)
  chatMessages.appendChild(bubble)
  chatMessages.scrollTop = chatMessages.scrollHeight
  return textEl
}

async function sendChatMessage() {
  const message = chatInput.value.trim()
  if (!message || !lastTranscript) return

  chatInput.value = ''
  chatSendBtn.disabled = true
  chatInput.disabled = true

  appendChatBubble('user', message)
  const loadingEl = appendChatBubble('model', '', true)

  const result = await window.electronAPI.chatMessage(lastTranscript, chatHistory, message)

  if (!result.ok) {
    loadingEl.textContent = `Error: ${result.error}`
    loadingEl.classList.remove('loading')
  } else {
    loadingEl.textContent = result.response
    loadingEl.classList.remove('loading')
    chatHistory.push({ role: 'user', content: message })
    chatHistory.push({ role: 'model', content: result.response })
  }

  chatSendBtn.disabled = false
  chatInput.disabled = false
  chatInput.focus()
}

chatSendBtn.addEventListener('click', sendChatMessage)
chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage() }
})

// ── Monday.com ────────────────────────────────────────────────────
async function showMondaySection() {
  mondaySection.classList.remove('hidden')
  mondayStatusText.textContent = ''

  if (!mondayProjectsLoaded) {
    mondayProjectSelect.innerHTML = '<option value="">Cargando proyectos...</option>'
    mondayPublishBtn.disabled = true

    const result = await window.electronAPI.mondayGetProjects()
    if (result.ok && result.data?.length) {
      mondayProjectSelect.innerHTML = '<option value="">Seleccionar proyecto...</option>'
      result.data.forEach(item => {
        const opt = document.createElement('option')
        opt.value = item.id
        opt.textContent = item.name
        mondayProjectSelect.appendChild(opt)
      })
      mondayProjectsLoaded = true
    } else {
      mondayProjectSelect.innerHTML = '<option value="">Sin proyectos — configura Monday.com</option>'
    }
  }

  mondayPublishBtn.disabled = !mondayProjectSelect.value
}

mondayProjectSelect.addEventListener('change', () => {
  mondayPublishBtn.disabled = !mondayProjectSelect.value
  mondayStatusText.textContent = ''
})

mondayPublishBtn.addEventListener('click', async () => {
  if (!currentActaData || !mondayProjectSelect.value) return
  mondayPublishBtn.disabled = true
  mondayPublishBtn.textContent = 'Publicando...'

  const result = await window.electronAPI.mondayPublishActa(mondayProjectSelect.value, currentActaData)

  mondayPublishBtn.disabled = false
  mondayPublishBtn.textContent = 'Publicar'

  if (!result.ok) {
    mondayStatusText.textContent = `Error: ${result.error}`
    mondayStatusText.className = 'inline-status error'
  } else {
    mondayStatusText.textContent = 'Acta publicada en Monday.com correctamente.'
    mondayStatusText.className = 'inline-status success'
  }
})

async function autoPublish(actaData) {
  const itemId = mondayProjectSelect.value
  if (!itemId) return
  mondayStatusText.textContent = 'Publicando automáticamente...'
  const result = await window.electronAPI.mondayPublishActa(itemId, actaData)
  if (!result.ok) {
    mondayStatusText.textContent = `Auto-publicación fallida: ${result.error}`
    mondayStatusText.className = 'inline-status error'
  } else {
    mondayStatusText.textContent = 'Acta publicada automáticamente en Monday.com.'
    mondayStatusText.className = 'inline-status success'
  }
}

// ── Recording ─────────────────────────────────────────────────────
function formatTime(s) {
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

function startTimer() {
  secondsElapsed = 0
  timerEl.textContent = '00:00'
  timerEl.classList.remove('hidden')
  timerInterval = setInterval(() => {
    secondsElapsed++
    timerEl.textContent = formatTime(secondsElapsed)
  }, 1000)
}

function stopTimer() {
  clearInterval(timerInterval)
  timerEl.classList.add('hidden')
}

recordBtn.addEventListener('click', () => {
  if (!isRecording) startRecording()
  else stopRecording()
})

async function startRecording() {
  statusText.textContent = 'Iniciando captura...'
  let stream
  try {
    stream = await getMixedAudioStream()
  } catch (err) {
    statusText.textContent = `No se pudo acceder al audio: ${err.message}`
    startPreviewMeters()
    return
  }

  audioChunks = []
  mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })
  mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data) }
  mediaRecorder.onstop = handleRecordingStop
  mediaRecorder.start(1000)

  isRecording = true
  recordBtn.textContent = '■'
  recordBtn.classList.add('recording')
  apiDot.classList.remove('ready')
  apiDot.classList.add('recording')
  startTimer()
  statusText.textContent = 'Grabando...'
}

function stopRecording() {
  if (mediaRecorder?.state !== 'inactive') {
    mediaRecorder.stop()
    mediaRecorder.stream.getTracks().forEach(t => t.stop())
  }
  stopMeter(micFrameRef, barMic)
  stopMeter(systemFrameRef, barSystem)
  if (audioContext) { audioContext.close(); audioContext = null }
  micGainNode = null
  stopTimer()
  isRecording = false
  recordBtn.textContent = '●'
  recordBtn.classList.remove('recording')
  apiDot.classList.remove('recording')
  apiDot.classList.add('ready')
  statusText.textContent = 'Procesando...'
}

async function handleRecordingStop() {
  const blob = new Blob(audioChunks, { type: 'audio/webm;codecs=opus' })
  statusText.textContent = 'Guardando y enviando a transcripción...'

  const arrayBuffer = await blob.arrayBuffer()
  const result = await window.electronAPI.transcribeAudio(arrayBuffer, recordProfileSelect.value || null)

  if (!result.ok) {
    statusText.textContent = `Error: ${result.error}`
    startPreviewMeters()
    return
  }

  jobs[result.job_id] = {
    id: result.job_id,
    status: 'running',
    file_name: result.savedPath?.split(/[/\\]/).pop() || `recording_${result.job_id}.webm`,
    chunks_done: 0,
    total_chunks: 0,
    created_at: new Date().toISOString()
  }
  renderJobSidebar()

  statusText.textContent = 'Transcripción en cola — puedes grabar otra reunión.'
  setTimeout(() => { if (!isRecording) statusText.textContent = 'Listo para grabar' }, 5000)

  startPreviewMeters()
}

// ── Audio stream helpers ──────────────────────────────────────────
async function getMixedAudioStream() {
  const useMic = toggleMic.checked
  const useSystem = toggleSystem.checked
  if (!useMic && !useSystem) throw new Error('Activa al menos una fuente de audio.')

  stopPreviewMeters()
  audioContext = new AudioContext()
  const destination = audioContext.createMediaStreamDestination()

  if (useSystem) {
    const sources = await window.electronAPI.getSources()
    const desktopStream = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: 'desktop', chromeMediaSourceId: sources[0].id } },
      video: { mandatory: { chromeMediaSource: 'desktop', chromeMediaSourceId: sources[0].id, maxWidth: 1, maxHeight: 1, maxFrameRate: 1 } }
    })
    desktopStream.getVideoTracks().forEach(t => t.stop())
    const tracks = desktopStream.getAudioTracks()
    if (tracks.length === 0) throw new Error('No se capturó audio del sistema.')
    const sysSrc = audioContext.createMediaStreamSource(new MediaStream(tracks))
    systemAnalyser = audioContext.createAnalyser(); systemAnalyser.fftSize = 256
    sysSrc.connect(systemAnalyser)
    sysSrc.connect(destination)
    animateMeter(systemAnalyser, barSystem, systemFrameRef)
  }

  if (useMic) {
    try {
      const micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      micAnalyser = audioContext.createAnalyser(); micAnalyser.fftSize = 256
      micGainNode = audioContext.createGain()
      micGainNode.gain.value = 1
      const micSrc = audioContext.createMediaStreamSource(micStream)
      micSrc.connect(micAnalyser)
      micSrc.connect(micGainNode)
      micGainNode.connect(destination)
      animateMeter(micAnalyser, barMic, micFrameRef)
    } catch (err) {
      console.warn('[MayiHear] Mic unavailable:', err.message)
    }
  }

  return destination.stream
}

// ── Level meters ──────────────────────────────────────────────────
function animateMeter(analyser, barEl, frameRef) {
  const data = new Uint8Array(analyser.frequencyBinCount)
  function draw() {
    frameRef.current = requestAnimationFrame(draw)
    analyser.getByteFrequencyData(data)
    const avg = data.reduce((a, b) => a + b, 0) / data.length
    barEl.style.width = Math.min(100, (avg / 128) * 100) + '%'
  }
  draw()
}

function stopMeter(frameRef, barEl) {
  if (frameRef.current) { cancelAnimationFrame(frameRef.current); frameRef.current = null }
  barEl.style.width = '0%'
}

async function startPreviewMeters() {
  if (previewContext || isRecording) return
  try {
    previewContext = new AudioContext()
    if (toggleMic.checked) {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      micAnalyser = previewContext.createAnalyser(); micAnalyser.fftSize = 256
      previewContext.createMediaStreamSource(s).connect(micAnalyser)
      animateMeter(micAnalyser, barMic, micFrameRef)
    }
    if (toggleSystem.checked) {
      const sources = await window.electronAPI.getSources()
      const ds = await navigator.mediaDevices.getUserMedia({
        audio: { mandatory: { chromeMediaSource: 'desktop', chromeMediaSourceId: sources[0].id } },
        video: { mandatory: { chromeMediaSource: 'desktop', chromeMediaSourceId: sources[0].id, maxWidth: 1, maxHeight: 1, maxFrameRate: 1 } }
      })
      ds.getVideoTracks().forEach(t => t.stop())
      if (ds.getAudioTracks().length > 0) {
        systemAnalyser = previewContext.createAnalyser(); systemAnalyser.fftSize = 256
        previewContext.createMediaStreamSource(new MediaStream(ds.getAudioTracks())).connect(systemAnalyser)
        animateMeter(systemAnalyser, barSystem, systemFrameRef)
      }
    }
  } catch (err) {
    console.warn('[MayiHear] Preview meters:', err.message)
  }
}

function stopPreviewMeters() {
  stopMeter(micFrameRef, barMic)
  stopMeter(systemFrameRef, barSystem)
  if (previewContext) { previewContext.close(); previewContext = null }
  micAnalyser = null; systemAnalyser = null
}

toggleMic.addEventListener('change', async () => {
  if (isRecording && micGainNode) {
    micGainNode.gain.value = toggleMic.checked ? 1 : 0
    return
  }
  stopPreviewMeters()
  if (!isRecording) await startPreviewMeters()
})
toggleSystem.addEventListener('change', async () => { stopPreviewMeters(); if (!isRecording) await startPreviewMeters() })

// ── Import ────────────────────────────────────────────────────────
importToggleBtn.addEventListener('click', () => {
  const open = !importArea.classList.contains('hidden')
  importArea.classList.toggle('hidden', open)
  importToggleBtn.textContent = open ? 'Expandir ↓' : '✕ Cerrar'
})

cancelImportBtn.addEventListener('click', () => {
  importArea.classList.add('hidden')
  importToggleBtn.textContent = 'Expandir ↓'
  importTextarea.value = ''
  generateFromTextBtn.disabled = true
})

importTextarea.addEventListener('input', () => {
  generateFromTextBtn.disabled = !importTextarea.value.trim()
})

loadTxtBtn.addEventListener('click', async () => {
  const result = await window.electronAPI.loadTranscriptFile()
  if (!result.ok) return
  importTextarea.value = result.text
  generateFromTextBtn.disabled = !result.text.trim()
})

generateFromTextBtn.addEventListener('click', async () => {
  const text = importTextarea.value.trim()
  if (!text) return
  generateFromTextBtn.disabled = true
  generateFromTextBtn.textContent = 'Analizando...'

  // Show as an imported transcript in the detail area
  selectedJobId = null
  lastTranscript = text
  currentActaData = null
  chatHistory = []
  transcriptBox.textContent = text
  transcriptBox.classList.remove('loading')
  insightsBox.textContent = ''
  actaBox.textContent = ''
  actaEmptyState.classList.remove('hidden')
  actaReadyState.classList.add('hidden')
  mondaySection.classList.add('hidden')
  chatMessages.innerHTML = '<div class="chat-empty">Haz una pregunta sobre esta reunión para empezar.</div>'
  generateActaBtn.textContent = 'Generar Acta de Reunión'
  generateActaBtn.disabled = false

  jobDetailEmpty.style.display = 'none'
  jobDetailContent.classList.remove('hidden')
  switchSubTab('transcript')
  showPage('page-transcriptions')

  await runInsights(text)
  startPreviewMeters()

  generateFromTextBtn.disabled = false
  generateFromTextBtn.textContent = 'Analizar texto'
})

// ── Copy / Save ───────────────────────────────────────────────────
copyTranscriptBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(transcriptBox.textContent)
  copyTranscriptBtn.textContent = '¡Copiado!'
  setTimeout(() => { copyTranscriptBtn.textContent = 'Copiar' }, 1500)
})

saveTranscriptBtn.addEventListener('click', async () => {
  const text = transcriptBox.textContent
  if (!text) return
  const result = await window.electronAPI.saveTranscript(text)
  if (result.saved) {
    saveTranscriptBtn.textContent = '¡Guardado!'
    setTimeout(() => { saveTranscriptBtn.textContent = 'Guardar .txt' }, 2000)
  }
})

copyInsightsBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(insightsBox.textContent)
  copyInsightsBtn.textContent = '¡Copiado!'
  setTimeout(() => { copyInsightsBtn.textContent = 'Copiar' }, 1500)
})

// ── Folder ────────────────────────────────────────────────────────
openFolderBtn.addEventListener('click', () => window.electronAPI.openRecordingsFolder())

// ── Setup banner ──────────────────────────────────────────────────
setupBannerBtn.addEventListener('click', () => { openSettings(); loadSettingsIntoPanel() })

// ── Settings panel ────────────────────────────────────────────────
const settingsBtn       = document.getElementById('settings-btn')
const settingsPanel     = document.getElementById('settings-panel')
const settingsOverlay   = document.getElementById('settings-overlay')
const settingsCloseBtn  = document.getElementById('settings-close-btn')
const sGeminiKey        = document.getElementById('s-gemini-key')
const sGeminiToggle     = document.getElementById('s-gemini-toggle')
const sGeminiSaveBtn    = document.getElementById('s-gemini-save-btn')
const sGeminiStatus     = document.getElementById('s-gemini-status')
const sGeminiHint       = document.getElementById('s-gemini-hint')
const sLocalWhisper     = document.getElementById('s-local-whisper')
const sWhisperModelRow  = document.getElementById('s-whisper-model-row')
const sWhisperModel     = document.getElementById('s-whisper-model')
const sTranscriptionSaveBtn = document.getElementById('s-transcription-save-btn')
const sTranscriptionStatus  = document.getElementById('s-transcription-status')
const sMondayToken      = document.getElementById('s-monday-token')
const sMondayBoardId    = document.getElementById('s-monday-board-id')
const sMondayColumnId   = document.getElementById('s-monday-column-id')
const sAutoPublish      = document.getElementById('s-auto-publish')
const sTokenToggle      = document.getElementById('s-token-toggle')
const sSaveBtn          = document.getElementById('s-save-btn')
const sTestBtn          = document.getElementById('s-test-btn')
const sSaveStatus       = document.getElementById('s-save-status')
const sBoardSelect      = document.getElementById('s-board-select')
const sBoardMetrics     = document.getElementById('s-board-metrics')
const sBoardLoading     = document.getElementById('s-board-loading')
const sBoardName        = document.getElementById('s-board-name')
const sBoardCount       = document.getElementById('s-board-count')
const sBoardDesc        = document.getElementById('s-board-desc')
const sBoardGroups      = document.getElementById('s-board-groups')
const sBoardColumns     = document.getElementById('s-board-columns')

const sPickDirBtn   = document.getElementById('s-pick-dir-btn')
const sRecordingsPath = document.getElementById('s-recordings-path')
const sDirStatus    = document.getElementById('s-dir-status')
const sVertexPickBtn      = document.getElementById('s-vertex-pick-btn')
const sVertexClearBtn     = document.getElementById('s-vertex-clear-btn')
const sVertexHint         = document.getElementById('s-vertex-hint')
const sVertexStatus       = document.getElementById('s-vertex-status')
const sActiveBackendBadge = document.getElementById('s-active-backend-badge')

sPickDirBtn.addEventListener('click', async () => {
  const result = await window.electronAPI.pickRecordingsDir()
  if (!result.ok) return
  sRecordingsPath.textContent = result.path
  recordingsPathText.textContent = result.path
  sDirStatus.textContent = 'Carpeta actualizada.'
  sDirStatus.className = 'sp-status success'
  autoHideStatus(sDirStatus, 3000)
})

function openSettings() {
  settingsPanel.classList.remove('hidden')
  settingsOverlay.classList.remove('hidden')
}

function closeSettings() {
  settingsPanel.classList.add('hidden')
  settingsOverlay.classList.add('hidden')
}

settingsBtn.addEventListener('click', async () => { openSettings(); await loadSettingsIntoPanel(); loadBoardsIntoExplorer() })
settingsCloseBtn.addEventListener('click', closeSettings)
settingsOverlay.addEventListener('click', closeSettings)

sGeminiToggle.addEventListener('click', () => {
  sGeminiKey.type = sGeminiKey.type === 'password' ? 'text' : 'password'
})

sGeminiSaveBtn.addEventListener('click', async () => {
  const key = sGeminiKey.value.trim()
  if (!key) { setSpStatus(sGeminiStatus, 'Ingresa tu clave Gemini.', 'error'); return }
  setSpStatus(sGeminiStatus, 'Guardando...', '')
  const result = await window.electronAPI.saveSettings({ gemini_api_key: key })
  if (result.ok) {
    sGeminiKey.value = ''
    sGeminiHint.textContent = `...${key.slice(-4)}`
    setSpStatus(sGeminiStatus, 'Clave guardada. Ya puedes transcribir.', 'success')
    appSettings.gemini_configured = true
    setupBanner.classList.add('hidden')
  } else {
    setSpStatus(sGeminiStatus, 'Error al guardar.', 'error')
  }
  autoHideStatus(sGeminiStatus, 3000)
})

sVertexPickBtn.addEventListener('click', async () => {
  const result = await window.electronAPI.pickVertexCredentials()
  if (!result.ok) return
  const fileName = result.path.split(/[\\/]/).pop()
  sVertexHint.textContent = fileName
  sVertexClearBtn.classList.remove('hidden')
  setSpStatus(sVertexStatus, 'Credenciales de Vertex AI configuradas.', 'success')
  autoHideStatus(sVertexStatus, 3000)
  await refreshBackendBadge()
})

sVertexClearBtn.addEventListener('click', async () => {
  await window.electronAPI.clearVertexCredentials()
  sVertexHint.textContent = 'Sin configurar'
  sVertexClearBtn.classList.add('hidden')
  setSpStatus(sVertexStatus, 'Credenciales eliminadas.', 'success')
  autoHideStatus(sVertexStatus, 3000)
  await refreshBackendBadge()
})

sLocalWhisper.addEventListener('change', () => {
  sWhisperModelRow.classList.toggle('hidden', !sLocalWhisper.checked)
})

sTranscriptionSaveBtn.addEventListener('click', async () => {
  const mode = sLocalWhisper.checked ? 'local' : 'gemini'
  const model = sWhisperModel.value
  setSpStatus(sTranscriptionStatus, 'Guardando...', '')
  const result = await window.electronAPI.saveSettings({ transcription_mode: mode, whisper_model: model })
  if (result.ok) {
    setSpStatus(sTranscriptionStatus, mode === 'local' ? `Modo local (${model}) activo.` : 'Modo Gemini activo.', 'success')
  } else {
    setSpStatus(sTranscriptionStatus, 'Error al guardar.', 'error')
  }
  autoHideStatus(sTranscriptionStatus, 4000)
})

sTokenToggle.addEventListener('click', () => {
  sMondayToken.type = sMondayToken.type === 'password' ? 'text' : 'password'
})

sSaveBtn.addEventListener('click', async () => {
  setSpStatus(sSaveStatus, 'Guardando...', '')
  const result = await window.electronAPI.saveSettings({
    monday_token:        sMondayToken.value.trim(),
    monday_board_id:     sMondayBoardId.value.trim(),
    monday_column_id:    sMondayColumnId.value.trim(),
    monday_auto_publish: sAutoPublish.checked
  })
  if (result.ok) {
    appSettings.monday_auto_publish = sAutoPublish.checked
    setSpStatus(sSaveStatus, 'Guardado correctamente.', 'success')
  } else {
    setSpStatus(sSaveStatus, 'Error al guardar.', 'error')
  }
  autoHideStatus(sSaveStatus, 3000)
})

sTestBtn.addEventListener('click', async () => {
  sTestBtn.textContent = 'Probando...'
  sTestBtn.disabled = true
  const result = await window.electronAPI.mondayTestConnection()
  if (result.ok) {
    setSpStatus(sSaveStatus, `Conexión OK — ${result.boards_count} tablero(s).`, 'success')
    loadBoardsIntoExplorer()
  } else {
    setSpStatus(sSaveStatus, `Sin conexión: ${result.error}`, 'error')
  }
  sTestBtn.textContent = 'Probar conexión'
  sTestBtn.disabled = false
  autoHideStatus(sSaveStatus, 4000)
})

async function refreshBackendBadge() {
  if (!sActiveBackendBadge) return
  const status = await window.electronAPI.settingsStatus()
  if (!status.ok) { sActiveBackendBadge.textContent = ''; return }
  if (status.active_backend === 'vertex_ai') {
    sActiveBackendBadge.textContent = `Usando: Vertex AI${status.vertex_project ? ` (${status.vertex_project})` : ''}`
    sActiveBackendBadge.classList.add('freeform')
  } else {
    sActiveBackendBadge.textContent = 'Usando: AI Studio (clave Gemini)'
    sActiveBackendBadge.classList.remove('freeform')
  }
}

async function loadSettingsIntoPanel() {
  const s = await window.electronAPI.getSettings()
  appSettings = s
  const dirResult = await window.electronAPI.getRecordingsDir()
  if (dirResult.ok) sRecordingsPath.textContent = dirResult.path
  renderProfileSelectors()
  sGeminiKey.value = ''
  sGeminiHint.textContent = s.gemini_configured ? `...${s.gemini_hint}` : 'Sin configurar — requerida para transcribir.'
  const vertexFile = s.vertex_sa_path ? s.vertex_sa_path.split(/[\\/]/).pop() : ''
  sVertexHint.textContent = vertexFile || 'Sin configurar'
  sVertexClearBtn.classList.toggle('hidden', !s.vertex_sa_path)
  await refreshBackendBadge()
  sMondayToken.value    = ''
  sMondayBoardId.value  = s.monday_board_id || ''
  sMondayColumnId.value = s.monday_column_id || ''
  sAutoPublish.checked  = !!s.monday_auto_publish
  sLocalWhisper.checked = s.transcription_mode === 'local'
  sWhisperModel.value   = s.whisper_model || 'small'
  sWhisperModelRow.classList.toggle('hidden', !sLocalWhisper.checked)
}

async function loadBoardsIntoExplorer() {
  sBoardSelect.innerHTML = '<option value="">Cargando tableros...</option>'
  const result = await window.electronAPI.mondayGetBoards()
  if (!result.ok || !result.data?.length) {
    sBoardSelect.innerHTML = '<option value="">No se pudieron cargar los tableros</option>'
    return
  }
  sBoardSelect.innerHTML = '<option value="">Seleccionar tablero para explorar...</option>'
  result.data.forEach(b => {
    const opt = document.createElement('option')
    opt.value = b.id
    opt.textContent = b.name
    sBoardSelect.appendChild(opt)
  })
}

sBoardSelect.addEventListener('change', async () => {
  const boardId = sBoardSelect.value
  sBoardMetrics.classList.add('hidden')
  if (!boardId) return
  sBoardLoading.classList.remove('hidden')

  const result = await window.electronAPI.mondayBoardDetails(boardId)
  sBoardLoading.classList.add('hidden')
  if (!result.ok) return

  const d = result.data
  sBoardName.textContent  = d.name
  sBoardCount.textContent = d.items_count != null ? `${d.items_count} ítems` : ''
  sBoardDesc.textContent  = d.description || ''

  sBoardGroups.innerHTML = ''
  ;(d.groups || []).forEach(g => {
    const el = document.createElement('div')
    el.className = 'board-metrics-group'
    el.innerHTML = `<span style="width:8px;height:8px;border-radius:2px;background:${g.color || 'var(--border)'};flex-shrink:0;display:inline-block"></span>${g.title}`
    sBoardGroups.appendChild(el)
  })

  sBoardColumns.innerHTML = ''
  ;(d.columns || []).forEach(c => {
    const el = document.createElement('div')
    el.className = 'board-metrics-col'
    const idEl = document.createElement('span')
    idEl.className = 'board-metrics-col-id'
    idEl.textContent = c.id
    idEl.title = 'Clic para copiar'
    idEl.addEventListener('click', () => {
      navigator.clipboard.writeText(c.id)
      idEl.textContent = '¡copiado!'
      setTimeout(() => { idEl.textContent = c.id }, 1500)
    })
    el.innerHTML = `<span style="flex:1;font-size:11px;color:var(--text-subtle)">${c.title}</span>`
    el.appendChild(idEl)
    const typeEl = document.createElement('span')
    typeEl.className = 'board-metrics-col-type'
    typeEl.textContent = c.type
    el.appendChild(typeEl)
    sBoardColumns.appendChild(el)
  })

  sBoardMetrics.classList.remove('hidden')
})

// ── Settings helpers ──────────────────────────────────────────────
function setSpStatus(el, msg, cls) {
  el.textContent = msg
  el.className = 'sp-status' + (cls ? ` ${cls}` : '')
}

function autoHideStatus(el, delay) {
  setTimeout(() => { el.textContent = '' }, delay)
}

// ── Profiles ──────────────────────────────────────────────────────
async function loadProfiles() {
  const result = await window.electronAPI.getProfiles()
  if (!result.ok) return
  profiles = result.data
  renderProfileSelectors()
  renderProfilesList()
}

function getProfileLabel(p) {
  return (p.track ? `[${p.track}] ` : '') + p.name
}

function renderProfileSelectors() {
  const defaultOpt = '<option value="">Default (sin perfil)</option>'

  function fillSelect(el, prevValue, fallback) {
    el.innerHTML = defaultOpt
    profiles.forEach(p => {
      const opt = document.createElement('option')
      opt.value = p.id
      opt.textContent = getProfileLabel(p)
      el.appendChild(opt)
    })
    el.value = profiles.find(p => p.id === prevValue) ? prevValue : (fallback || '')
  }

  fillSelect(recordProfileSelect, recordProfileSelect.value, appSettings.default_profile_id)
  fillSelect(jobProfileSelect, jobProfileSelect.value, appSettings.default_profile_id)
  fillSelect(sDefaultProfile, sDefaultProfile.value, appSettings.default_profile_id)
}

function renderProfilesList() {
  Array.from(profilesList.querySelectorAll('.job-item')).forEach(el => el.remove())
  if (profiles.length === 0) {
    profilesEmpty.style.display = 'block'
    return
  }
  profilesEmpty.style.display = 'none'
  profiles.forEach(p => {
    const item = document.createElement('div')
    item.className = 'job-item'
    if (editingProfile?.id === p.id) item.classList.add('selected')
    item.innerHTML = `
      <span class="job-item-dot done"></span>
      <div class="job-item-body">
        <div class="job-item-name">${p.name}</div>
        <div class="job-item-meta">${p.track || 'Sin track'}</div>
      </div>
      <button class="text-btn muted" data-del style="font-size:10px;padding:2px 5px;flex-shrink:0" title="Eliminar">✕</button>
    `
    item.querySelector('[data-del]').addEventListener('click', e => { e.stopPropagation(); deleteProfileItem(p.id, p.name) })
    item.addEventListener('click', () => openEditProfile(p))
    profilesList.appendChild(item)
  })
}

async function deleteProfileItem(profileId, name) {
  if (!confirm(`¿Eliminar el perfil "${name}"?`)) return
  const result = await window.electronAPI.deleteProfile(profileId)
  if (result.ok) {
    if (editingProfile?.id === profileId) hideProfileForm()
    await loadProfiles()
  }
}

function openEditProfile(profile) {
  editingProfile = profile
  profileFormTitle.textContent = `Editar: ${profile.name}`
  pfTrack.value = profile.track || ''
  pfName.value = profile.name || ''
  pfContext.value = profile.context_for_insights || ''
  pfActaTemplate.value = profile.acta_template || ''
  showProfileForm(1)
  renderProfilesList()
}

function openNewProfile() {
  editingProfile = null
  profileFormTitle.textContent = 'Nuevo perfil'
  pfTrack.value = ''
  pfName.value = ''
  pfContext.value = ''
  pfActaTemplate.value = ''
  showProfileForm(1)
  renderProfilesList()
}

function showProfileForm(step) {
  currentProfileStep = step
  profileDetailEmpty.style.display = 'none'
  profileFormArea.classList.remove('hidden')

  document.getElementById('profiles-step-1').classList.toggle('hidden', step !== 1)
  document.getElementById('profiles-step-2').classList.toggle('hidden', step !== 2)
  document.getElementById('profiles-step-3').classList.toggle('hidden', step !== 3)

  const labels = ['1 de 3 — Identificación', '2 de 3 — Contexto', '3 de 3 — Plantilla Acta']
  pfStepIndicator.textContent = `Paso ${labels[step - 1]}`

  pfBackBtn.classList.toggle('hidden', step === 1)
  pfNextBtn.classList.toggle('hidden', step === 3)
  pfSaveBtn.classList.toggle('hidden', step !== 3)
}

function hideProfileForm() {
  editingProfile = null
  profileFormArea.classList.add('hidden')
  profileDetailEmpty.style.display = ''
  renderProfilesList()
}

profilesNewBtn.addEventListener('click', () => {
  showPage('page-profiles')
  openNewProfile()
})

pfCancelBtn.addEventListener('click', hideProfileForm)
pfBackBtn.addEventListener('click', () => showProfileForm(currentProfileStep - 1))

pfNextBtn.addEventListener('click', () => {
  if (currentProfileStep === 1 && !pfName.value.trim()) { pfName.focus(); return }
  showProfileForm(currentProfileStep + 1)
})

pfSaveBtn.addEventListener('click', async () => {
  const profileData = {
    id: editingProfile?.id || null,
    name: pfName.value.trim(),
    track: pfTrack.value.trim(),
    context_for_insights: pfContext.value.trim(),
    acta_template: pfActaTemplate.value.trim()
  }
  if (!profileData.name) { pfName.focus(); return }
  pfSaveBtn.disabled = true
  pfSaveBtn.textContent = 'Guardando...'
  const result = await window.electronAPI.saveProfile(profileData)
  pfSaveBtn.disabled = false
  pfSaveBtn.textContent = 'Guardar perfil'
  if (result.ok) {
    await loadProfiles()
    hideProfileForm()
  }
})

profilesExportBtn.addEventListener('click', () => window.electronAPI.exportProfiles())

profilesImportBtn.addEventListener('click', async () => {
  const result = await window.electronAPI.importProfiles()
  if (result.ok && !result.canceled) await loadProfiles()
})

sDefaultProfileSaveBtn.addEventListener('click', async () => {
  const profileId = sDefaultProfile.value
  setSpStatus(sDefaultProfileStatus, 'Guardando...', '')
  const result = await window.electronAPI.setDefaultProfile(profileId || null)
  if (result.ok) {
    appSettings.default_profile_id = profileId
    recordProfileSelect.value = profileId
    setSpStatus(sDefaultProfileStatus, 'Perfil por defecto guardado.', 'success')
  } else {
    setSpStatus(sDefaultProfileStatus, 'Error al guardar.', 'error')
  }
  autoHideStatus(sDefaultProfileStatus, 3000)
})

// ── Boot ──────────────────────────────────────────────────────────
init()
