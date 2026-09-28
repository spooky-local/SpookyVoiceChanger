' Toggles mic passthrough on the TTS service. No window.
On Error Resume Next
Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
http.Open "GET", "http://127.0.0.1:8765/passthrough", False
http.Send
