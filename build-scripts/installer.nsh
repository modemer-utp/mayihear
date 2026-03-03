; customInit runs first — before NSIS checks for and calls the old uninstaller.
; This ensures no locked files when the old uninstaller tries to delete them.
!macro customInit
  ExecWait 'taskkill /F /IM mayihear-api.exe /T'
  ExecWait 'taskkill /F /IM MayiHear.exe /T'
  ; Give Windows time to fully release process handles before NSIS checks for running instances
  Sleep 3000
!macroend

!macro customInstall
  ExecWait 'taskkill /F /IM mayihear-api.exe /T'
  ExecWait 'taskkill /F /IM MayiHear.exe /T'
!macroend

!macro customUnInstall
  ExecWait 'taskkill /F /IM mayihear-api.exe /T'
  ExecWait 'taskkill /F /IM MayiHear.exe /T'
!macroend
