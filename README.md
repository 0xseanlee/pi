# Pi Station

繁體中文、手機優先的樹莓派靜態控制台，適用於 GitHub Pages。無需安裝套件或編譯。

## 目前功能

- 儲存樹莓派服務位址到目前瀏覽器，重新開啟會恢復。
- 清楚標示尚未連線；沒有模擬裝置數據。
- 控制區等待確認功能後再實作，目前不會傳送任何指令。

## 預覽

直接開啟 `index.html`，或在專案目錄執行 `python3 -m http.server 8080`，瀏覽 `http://localhost:8080`。

## GitHub Pages

將專案上傳到 GitHub repository 的 `main` 分支。在 repository 的 **Settings → Pages → Build and deployment → Source** 選擇 **GitHub Actions**。隨附工作流程會發布三個網頁檔案。若使用其他分支，請調整 `.github/workflows/pages.yml` 的分支名稱。

GitHub repository：https://github.com/0xseanlee/pi

控制台網址：https://0xseanlee.github.io/pi/

## 待接上的樹莓派服務

網頁是操作介面，實際指令需要由樹莓派上的服務執行。功能確認後再決定 API、連線驗證與服務部署方式。

同一個熱點下裝置能否互通，取決於熱點是否隔離用戶端。GitHub Pages 使用 HTTPS，連接區域網路服務還需處理瀏覽器的安全限制、跨來源設定和必要權限。只儲存 IP 位址不代表已建立可用連線；正式串接時需用實際手機、瀏覽器和熱點測試。

不要將密碼、存取 token 或可執行任意 shell 指令的入口放進公開的網頁程式碼。
