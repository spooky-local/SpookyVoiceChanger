' Fires the start action on the TTS service. No window.
On Error Resume Next
Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
http.Open "GET", "http://127.0.0.1:8765/start", False
http.Send
