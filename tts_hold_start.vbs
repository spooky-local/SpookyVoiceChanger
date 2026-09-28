' Hold-to-talk: BUTTON PRESS.
' Bind this to the press action of your mouse side button.
' Starts recording. Release fires tts_hold_end.vbs.
On Error Resume Next
Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
http.Open "GET", "http://127.0.0.1:8765/start", False
http.Send
