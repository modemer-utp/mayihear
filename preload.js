const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  // Audio capture
  getSources: () => ipcRenderer.invoke('get-sources'),

  // Recording + transcription
  transcribeAudio: (audioBuffer, profileId) => ipcRenderer.invoke('transcribe-audio', audioBuffer, profileId),
  getAllJobs: () => ipcRenderer.invoke('get-all-jobs'),
  getJobText: (jobId) => ipcRenderer.invoke('get-job-text', jobId),
  onJobUpdate: (callback) => ipcRenderer.on('job-update', (_event, data) => callback(data)),

  // File system
  getRecordingsDir: () => ipcRenderer.invoke('get-recordings-dir'),
  pickRecordingsDir: () => ipcRenderer.invoke('pick-recordings-dir'),
  openRecordingsFolder: () => ipcRenderer.invoke('open-recordings-folder'),
  saveTranscript: (text) => ipcRenderer.invoke('save-transcript', text),
  loadTranscriptFile: () => ipcRenderer.invoke('load-transcript-file'),

  // AI processing
  chatMessage: (transcript, history, message) => ipcRenderer.invoke('chat-message', transcript, history, message),
  generateInsights: (transcript, context, jobId) => ipcRenderer.invoke('generate-insights', transcript, context, jobId),
  generateMeetingAct: (transcript, context, actaTemplate) => ipcRenderer.invoke('generate-meeting-act', transcript, context, actaTemplate),
  downloadWord: (actaData) => ipcRenderer.invoke('download-word', actaData),

  // Monday.com
  mondayGetBoards: () => ipcRenderer.invoke('monday-get-boards'),
  mondayGetItems: (boardId) => ipcRenderer.invoke('monday-get-items', boardId),
  mondayGetColumns: (boardId) => ipcRenderer.invoke('monday-get-columns', boardId),
  mondayPublish: (boardId, itemId, columnId, actaData) => ipcRenderer.invoke('monday-publish', boardId, itemId, columnId, actaData),
  mondayGetProjects: () => ipcRenderer.invoke('monday-get-projects'),
  mondayPublishActa: (itemId, actaData) => ipcRenderer.invoke('monday-publish-acta', itemId, actaData),
  mondayBoardDetails: (boardId) => ipcRenderer.invoke('monday-board-details', boardId),
  mondayTestConnection: () => ipcRenderer.invoke('monday-test-connection'),

  // Vertex AI credentials
  pickVertexCredentials: () => ipcRenderer.invoke('pick-vertex-credentials'),
  clearVertexCredentials: () => ipcRenderer.invoke('clear-vertex-credentials'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  // Settings
  getSettings: () => ipcRenderer.invoke('get-settings'),
  saveSettings: (data) => ipcRenderer.invoke('save-settings', data),
  settingsStatus: () => ipcRenderer.invoke('settings-status'),

  // Profiles
  getProfiles: () => ipcRenderer.invoke('get-profiles'),
  saveProfile: (profile) => ipcRenderer.invoke('save-profile', profile),
  deleteProfile: (profileId) => ipcRenderer.invoke('delete-profile', profileId),
  exportProfiles: () => ipcRenderer.invoke('export-profiles'),
  importProfiles: () => ipcRenderer.invoke('import-profiles'),
  setDefaultProfile: (profileId) => ipcRenderer.invoke('set-default-profile', profileId),
})
