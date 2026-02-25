// ── Elements ──────────────────────────────────────────────────
const recordBtn       = document.getElementById('record-btn')
const statusText      = document.getElementById('status-text')
const statusDot       = document.getElementById('status-dot')
const timerEl         = document.getElementById('timer')
const contextInput    = document.getElementById('context-input')
const transcriptSection = document.getElementById('transcript-section')
const transcriptBox   = document.getElementById('transcript-box')
const insightsSection = document.getElementById('insights-section')
const insightsBox     = document.getElementById('insights-box')
const copyTranscript  = document.getElementById('copy-transcript')
const copyInsights    = document.getElementById('copy-insights')

// ── State ──────────────────────────────────────────────────────
let mediaRecorder = null
let audioChunks   = []
let timerInterval = null
let secondsElapsed = 0
let isRecording   = false
let audioContext  = null  // kept alive during recording, closed on stop

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

// ── Get mixed audio stream: system loopback + microphone ───────
// Same approach as OBS — captures each source separately then merges them
async function getMixedAudioStream() {
  // ── 1. System audio (loopback) — captures Teams/Zoom remote participants ──
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
  console.log(`[MayiHear] System audio tracks: ${systemTracks.length}`)
  systemTracks.forEach((t, i) => console.log(`  System ${i}: ${t.label}`))

  if (systemTracks.length === 0) {
    throw new Error('No system audio captured. Enable "Stereo Mix" in Windows Sound settings → Recording tab.')
  }

  // ── 2. Microphone — captures your own voice ──────────────────
  let micStream = null
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
    console.log(`[MayiHear] Microphone: ${micStream.getAudioTracks()[0]?.label}`)
  } catch (err) {
    console.warn('[MayiHear] Microphone not available — recording system audio only:', err.message)
    setStatus('Recording (system audio only — mic not available)...')
  }

  // ── 3. Mix both sources via Web Audio API (same as OBS) ──────
  audioContext = new AudioContext()
  const destination = audioContext.createMediaStreamDestination()

  const systemSource = audioContext.createMediaStreamSource(new MediaStream(systemTracks))
  systemSource.connect(destination)

  if (micStream) {
    const micSource = audioContext.createMediaStreamSource(micStream)
    micSource.connect(destination)
  }

  console.log(`[MayiHear] Mixed stream ready — sources: system${micStream ? ' + mic' : ' only'}`)
  return destination.stream
}

// ── Start recording ────────────────────────────────────────────
async function startRecording() {
  setStatus('Starting capture...')

  let stream
  try {
    stream = await getMixedAudioStream()
  } catch (err) {
    setStatus(`Could not access audio: ${err.message}`)
    console.error(err)
    return
  }

  audioChunks = []
  mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })

  mediaRecorder.ondataavailable = e => {
    if (e.data.size > 0) audioChunks.push(e.data)
  }

  mediaRecorder.onstop = handleRecordingStop

  mediaRecorder.start(1000) // collect chunks every 1s
  setRecordingUI(true)
  startTimer()
  setStatus('Recording...')

  // Clear previous outputs when starting a new recording
  hideOutputs()
}

// ── Stop recording ─────────────────────────────────────────────
function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
    mediaRecorder.stream.getTracks().forEach(t => t.stop())
  }
  // Close the AudioContext used for mixing
  if (audioContext) {
    audioContext.close()
    audioContext = null
  }
  stopTimer()
  setRecordingUI(false)
  setStatus('Processing...')
}

// ── After recording stops — transcribe then get insights ───────
async function handleRecordingStop() {
  const blob = new Blob(audioChunks, { type: 'audio/webm;codecs=opus' })
  const arrayBuffer = await blob.arrayBuffer()

  // ── Transcription ──
  setStatus('Transcribing...')
  showPanel(transcriptSection)
  transcriptBox.textContent = 'Transcribing audio...'
  transcriptBox.classList.add('loading')

  const transcribeResult = await window.electronAPI.transcribeAudio(arrayBuffer)

  if (!transcribeResult.ok) {
    transcriptBox.textContent = `Error: ${transcribeResult.error}`
    transcriptBox.classList.remove('loading')
    setStatus('Transcription failed.')
    return
  }

  const transcript = transcribeResult.text
  console.log(`[MayiHear] Transcript received (${transcript.length} chars):`, transcript || '(empty)')

  if (!transcript.trim()) {
    transcriptBox.textContent = 'No speech detected. Make sure audio is playing through your speakers/headphones during the recording.'
    transcriptBox.classList.remove('loading')
    setStatus('No speech detected.')
    return
  }

  transcriptBox.textContent = transcript
  transcriptBox.classList.remove('loading')

  // ── Insights ──
  setStatus('Generating insights...')
  showPanel(insightsSection)
  insightsBox.textContent = 'Analyzing transcript...'
  insightsBox.classList.add('loading')

  const context = contextInput.value.trim()
  const insightsResult = await window.electronAPI.generateInsights(transcript, context)

  if (!insightsResult.ok) {
    insightsBox.textContent = `Error: ${insightsResult.error}`
    insightsBox.classList.remove('loading')
    setStatus('Insights failed.')
    return
  }

  const insightsText = insightsResult.text?.trim()
  insightsBox.textContent = insightsText || 'Insights returned empty. Check the terminal logs for the raw API response.'
  insightsBox.classList.remove('loading')
  setStatus('Done.')
}

// ── UI helpers ─────────────────────────────────────────────────
function showPanel(el) {
  el.classList.add('visible')
}

function hideOutputs() {
  transcriptSection.classList.remove('visible')
  insightsSection.classList.remove('visible')
  transcriptBox.textContent = ''
  insightsBox.textContent = ''
}

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
  copyTranscript.textContent = 'Copied!'
  setTimeout(() => { copyTranscript.textContent = 'Copy' }, 1500)
})

copyInsights.addEventListener('click', () => {
  navigator.clipboard.writeText(insightsBox.textContent)
  copyInsights.textContent = 'Copied!'
  setTimeout(() => { copyInsights.textContent = 'Copy' }, 1500)
})
