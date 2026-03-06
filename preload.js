const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  getSources: () =>
    ipcRenderer.invoke('get-sources'),

  transcribeAudio: (audioBuffer) =>
    ipcRenderer.invoke('transcribe-audio', audioBuffer),

  generateInsights: (transcript, context) =>
    ipcRenderer.invoke('generate-insights', transcript, context),

  saveTranscript: (text) =>
    ipcRenderer.invoke('save-transcript', text),

  generateMeetingAct: (transcript, context) =>
    ipcRenderer.invoke('generate-meeting-act', transcript, context),

  downloadWord: (actaData) =>
    ipcRenderer.invoke('download-word', actaData),

  mondayGetBoards: () =>
    ipcRenderer.invoke('monday-get-boards'),

  mondayGetItems: (boardId) =>
    ipcRenderer.invoke('monday-get-items', boardId),

  mondayGetColumns: (boardId) =>
    ipcRenderer.invoke('monday-get-columns', boardId),

  mondayPublish: (boardId, itemId, columnId, actaData) =>
    ipcRenderer.invoke('monday-publish', boardId, itemId, columnId, actaData)
})
