# Pi Station

繁體中文、手機優先的樹莓派靜態控制台，適用於 GitHub Pages。無需安裝套件或編譯。

## 目前功能

- 開啟頁面就自動尋找 `sean`，不需要輸入位址。
- 支援直接存取本機服務的瀏覽器會嘗試 `sean.local:8000`、上次成功位址與已知的 iPhone 熱點小網段；找到後每 10 秒確認一次，找不到每 15 秒重試。
- iPhone Safari 從 GitHub HTTPS 頁面自動前往 `http://sean.local:8000/`；樹莓派提供相同控制台，在同來源檢查服務。這是自動轉往本機頁面，不是宣稱 Safari 可從 GitHub 頁面直接掃描 HTTP 區域網路。
- 只有收到正確的 Pi Station 辨識回應且主機名稱為 `sean` 才顯示找到裝置。這是辨識，不是存取授權；未提供控制指令 API。
- 控制區等待確認功能後再實作，目前不會傳送任何指令。

## 預覽

在專案目錄執行 `python3 -m http.server 8080`，瀏覽 `http://localhost:8080`。直接開啟本機 HTML 檔案僅能預覽外觀，辨識服務不允許 `file://` 的跨來源請求。

## GitHub Pages

將專案上傳到 GitHub repository 的 `main` 分支。在 repository 的 **Settings → Pages → Build and deployment → Source** 選擇 **GitHub Actions**。隨附工作流程會發布三個網頁檔案。若使用其他分支，請調整 `.github/workflows/pages.yml` 的分支名稱。

GitHub repository：https://github.com/0xseanlee/pi

控制台網址：https://0xseanlee.github.io/pi/

## 樹莓派辨識服務

`raspberry-pi/device-server.py` 在連接埠 8000 提供 `/api/v1/identity` 與三個控制台靜態檔案，由 `pi-station-device.service` 開機自動啟動。控制台檔案安裝在 `/opt/pi-station/web`，程式在 `/usr/local/lib/pi-station/device-server.py`，使用 `sean` 帳號執行。

Safari 的自動前往依賴手機可解析 `sean.local` 並存取熱點內的 Pi；無法保證所有熱點都支援裝置互通或 Bonjour。若本機名稱無法解析，該方式會停在瀏覽器連線錯誤頁，需要確認實際網路環境。支援 Local Network Access 的瀏覽器可能要求區域網路權限；不要停用瀏覽器安全防護。相關限制見 [MDN](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Local_network_access)。

辨識服務為唯讀，不讀取 Wi-Fi 設定、密碼或任意本機檔案，CORS 只允許這個控制台的網域及指定本機預覽來源。實際控制指令與登入驗證待功能確認後再實作。

驗證前端自動搜尋流程：`node --test tests/discovery.test.cjs`。

不要將密碼、存取 token 或可執行任意 shell 指令的入口放進公開的網頁程式碼。

## 樹莓派的 Wi-Fi 切換

樹莓派端可用 NetworkManager 儲存優先熱點，再用 systemd timer 偵測並切換。程式與操作說明見 [raspberry-pi](raspberry-pi/README.md)；網頁本身不會替樹莓派設定 Wi-Fi。
