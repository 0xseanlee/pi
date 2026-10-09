# Pi Station

繁體中文、手機優先的樹莓派控制台。GitHub Pages 提供入口，樹莓派提供 HTTPS 登入與裝置 API。

控制台入口：[0xseanlee.me/pi](https://0xseanlee.me/pi/) · [GitHub](https://github.com/0xseanlee/pi)

## 使用

1. 樹莓派連上你的熱點或同一個區域網路。
2. 開啟控制台入口。iPhone Safari 會自動前往 [sean.local:8443](https://sean.local:8443/)，不用輸入 IP。
3. 第一次使用時，Safari 會提示本機憑證未受信任。請本人核對這台 Pi 的憑證，再決定是否信任這個網站。不要直接信任其他裝置或不同憑證。
4. 帳號固定 `sean`，自行輸入樹莓派的帳號密碼。密碼由 Pi 的 PAM 驗證，原密碼不會寫進網頁、GitHub、瀏覽器儲存空間或應用程式日誌。
5. 登入有效期 30 分鐘。離開共用裝置前請按「登出」。控制功能等待指定，目前沒有執行指令的 API。

本機憑證 SHA-256（透過既有 SSH 連線取得）：

```text
A3:47:19:62:84:F3:D5:90:B2:77:01:A9:C1:F7:5D:E0:C9:C1:34:65:C2:25:C2:51:B6:B0:90:1D:6B:85:C8:19
```

憑證主體 `sean.local`，有效至 2027-10-09。憑證重新簽發後須透過可信管道重新核對指紋。這不是公開 CA 簽發的憑證；HTTPS 的裝置身分保障取決於首次正確核對與信任。Safari 憑證說明見 [Apple](https://support.apple.com/en-au/guide/iphone/iph1b914c6d4/ios)。不需安裝可替其他網站簽發憑證的根 CA。

## 自動尋找

- iPhone Safari 從公開 HTTPS 網頁直接轉往 Pi 的 HTTPS 控制台，再檢查同來源服務；不宣稱 Safari 可以直接從 GitHub 網頁掃描 HTTP 區域網路。
- 支援本機網路請求的瀏覽器會嘗試上次成功位址、`sean.local:8000`、已知家用位址與 iPhone 熱點小網段 `172.20.10.2` 至 `.14`；找到登入服務後轉往該 Pi 的 HTTPS 頁面。
- 公開搜尋端點只回傳固定的服務識別與登入需求，不會回傳裝置狀態。搜尋到服務不代表通過身分驗證；必須核對 HTTPS 憑證並登入。
- 本機頁面每 10 秒檢查服務與登入是否仍有效；未找到每 15 秒重試。
- 自動前往依賴手機能解析 `sean.local` 並連到熱點內的 Pi。網路若限制裝置互通或 Bonjour，仍可能需要進階手動位址。不要停用瀏覽器安全防護。網路限制見 [MDN](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Local_network_access)。

## 登入與服務

- HTTP `:8000` 只提供 `/api/v1/discovery` 和轉往 HTTPS 的導向，拒絕密碼登入與裝置 API。
- HTTPS `:8443` 提供三個靜態網頁檔案、`/api/v1/session`、`/api/v1/login`、`/api/v1/logout`，以及需要登入的 `/api/v1/identity`。
- `device-server.py` 以 `sean` 執行，透過受 Unix socket 權限與 peer UID 限制的 root PAM broker `auth-server.py` 驗證帳密，不以 root 執行網頁服務。
- PAM broker 只接受 `sean`，不提供任意帳號、shell 或密碼修改功能，並檢查帳號是否允許登入。
- Session 使用伺服器端亂數 token 與 `__Host-`、`Secure`、`HttpOnly`、`SameSite=Strict` cookie。登入時更新 token，登出時失效；服務重啟亦會清除。
- POST 必須使用同來源、JSON；已登入的修改操作還需要 CSRF token。登入限制每個來源 IP 每分鐘 5 次、全體每分鐘 20 次，超限回應 429。最多 32 個有效 session。
- 未登入的裝置 API 回應 401；登出、錯誤密碼、失效 session 不能繼續取得裝置狀態。未實作的控制 API 不會執行任何指令。
- 不允許任意檔案存取；只提供明列的靜態檔案。HTTP 與 HTTPS 兩個 listener 各限制 32 個並行請求並設逾時。

部署檔案位置與更新方式見 [raspberry-pi](raspberry-pi/README.md)。TLS 使用 Python 標準函式庫，見 [Python ssl 文件](https://docs.python.org/3/library/ssl.html)；帳號授權依 [PAM account management](https://pubs.opengroup.org/onlinepubs/8329799/pam_acct_mgmt.htm)。

## 驗證

```sh
node --test tests/discovery.test.cjs
python3 -m unittest discover -s tests -p 'test_*.py'
```

後端測試建立暫時憑證，在真實 TLS socket 上使用測試專用帳密檢查未登入阻擋、HTTP 拒絕登入、Host/Origin 限制、cookie、CSRF、登出、到期與登入限速。正式 Pi 使用系統 PAM；測試帳密不會安裝到正式 Pi。

GitHub Actions 由 `main` 發布 `index.html`、`style.css`、`app.js`。程式不需前端編譯；TLS 私鑰、Wi-Fi 密碼、SSH 密碼不放進 repository。
