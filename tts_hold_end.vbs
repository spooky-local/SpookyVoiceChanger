' Hold-to-talk: BUTTON RELEASE.
' Bind this to the release action of your mouse side button.
' Stops recording and renders. Autoplay (if on in the panel) plays it.
On Error Resume Next
Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
http.Open "GET", "http://127.0.0.1:8765/render", False
http.Send
