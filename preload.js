const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  getSources: () =>
    ipcRenderer.invoke('get-sources'),

  transcribeAudio: (audioBuffer) =>
    ipcRenderer.invoke('transcribe-audio', audioBuffer),

  generateInsights: (transcript, context) =>
    ipcRenderer.invoke('generate-insights', transcript, context)
})
