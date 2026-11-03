# Pi Station 管理工作台 v1

繁體中文、手機優先的樹莓派管理網站。舊版搜尋介面作為入口輔助，主體是檔案、程式、背景任務與 Terminal。

入口：[GitHub Pages](https://0xseanlee.github.io/pi/)。v1.1 保持在 GitHub 網頁操作，不再自動跳轉到區網頁面；手機與 Pi 仍需在同一網路。

## v1.1 介面更新

白底介面，只保留欄位、按鈕、狀態與必要限制。移除大型 π、裝飾性英文、宣傳標語和重複說明。

GitHub 頁面直接呼叫 Pi HTTPS API，跨來源登入回傳的 bearer token 僅存在當次頁面記憶體，重新整理後需重新登入。不使用第三方 Cookie，不將 token 存到 localStorage。只允許既有明列的 GitHub／自訂網域來源，仍檢查 Origin、登入及 CSRF。瀏覽器可能要求區網權限；自簽憑證須先確認信任，頁面提供另開分頁的「檢查裝置憑證」連結，沒有自動轉址。

已裝 v1 的 Pi 可使用 update-console.py 更新前端及 device HTTP API，校驗雜湊並備份、失敗還原；不重裝套件、不更換憑證，也不更動 auth、Wi-Fi 或 HSSH 服務。

## 功能

- 真正的 SSH 登入：Pi broker 使用輸入的 sean 帳密連接 127.0.0.1:22，固定本機 ED25519 主機公開金鑰。驗證後建立 HTTPS session，密碼不存入瀏覽器或 GitHub。
- 檔案：sean 家目錄瀏覽、建立檔案／資料夾、UTF-8 編輯、改名、上傳下載。單檔 8 MiB，上傳不覆蓋同名檔。檔案 API 拒絕越出家目錄的路徑和外連符號連結。
- 執行：儲存並執行 .py、.sh、.js；需對應執行環境。C/C++ 可在 Terminal 編譯。
- Terminal：真實 PTY＋bash，互動輸入及 Ctrl+C。文字模式，不支援 vim/top 等全螢幕介面。全體上限 8 個，每個登入 2 個，閒置 15 分鐘或登出時關閉。
- 背景任務：systemd 使用者服務，啟動、停止、重啟、日誌、建立時可選開機執行。網站關閉後仍運作，異常退出 5 秒後重啟，最多 50 個工作，不接管既有程序。
- 網路：查看目前連線、已存網路、附近 Wi-Fi，修改其他 Wi-Fi 優先序。手機熱點固定 999，其他網路最高 998。既有熱點切回及 HSSH 登入程式不改動。本版沒有新增網路或手動強制切換表單。

檔案 API 範圍是 sean 家目錄；Terminal 和使用者程式具 sean 一般權限，不是檔案 API 的沙箱。

## 安裝更新

適用已安裝 Pi Station、已有 sean 帳號及 TLS 私鑰的這台 Pi。正式發布使用指定 commit，避免 main 在下載期間改動。

```sh
curl -fL https://raw.githubusercontent.com/0xseanlee/pi/main/raspberry-pi/install-console.sh -o /tmp/install-console.sh
sudo sh /tmp/install-console.sh main
```

安裝器以同版本 manifest SHA-256 驗證程式，安裝 Paramiko、OpenSSL、polkitd，更新前端及 auth/device 服務。啟用 sean 的 user linger，讓背景任務不依賴 SSH 登入。安裝限定 sean 可透過 NetworkManager 修改系統連線的 polkit 規則；網頁 API 額外限制只能修改非熱點 Wi-Fi 優先序。Device 服務仍以 sean 執行，開放家目錄讀寫，其他系統路徑受 ProtectSystem 及一般使用者權限限制。

保留現有 TLS 私鑰，重簽包含目前 Wi-Fi IP、sean.local 及熱點小網段的憑證。請用安裝結果的 SHA-256 指紋核對；Safari 首次開啟會提示自簽憑證。IP 日後變更可能需要重簽或使用 sean.local。

iPhone 若無法解析 sean.local，直接使用已確認的 IP。瀏覽器不能直接使用原生 SSH，也不能保證自動列舉區網裝置；雲端 ChatGPT Work 無法直接掃描手機區網。

## 備份與還原

每次更新先備份被覆蓋檔案，路徑顯示於 /var/backups/pi-station/日期時間。中途失敗會嘗試還原檔案並重啟服務；已安裝套件與 user linger 不會自動撤銷。人工還原最近備份，在 Pi 執行：

```sh
sudo python3 - <<'PY'
import json, shutil, subprocess
from pathlib import Path
backup = sorted(Path('/var/backups/pi-station').glob('*/files.json'))[-1].parent
for name, existed in reversed(json.loads((backup/'files.json').read_text())):
    target = Path(name)
    if existed:
        shutil.copy2(backup/name.lstrip('/'), target)
    else:
        target.unlink(missing_ok=True)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'restart', 'pi-station-auth', 'pi-station-device'], check=True)
print('已還原', backup)
PY
```

## 驗證

```sh
node --test tests/discovery.test.cjs
node --check control.js
python3 -m unittest discover -s tests -p 'test_*.py'
```

測試涵蓋真實 TLS 登入、Host/Origin、Cookie、CSRF、未登入阻擋、路徑及符號連結、覆寫、PTY 執行、終端機登入隔離、背景 unit 指令隔離及熱點保護。HTTP 測試使用獨立驗證函式，不使用正式 Pi 密碼。正式 SSH、NetworkManager polkit、systemd 需在 Pi 實測；iPhone Safari 尚未實機驗證。

GitHub Pages 只發布四個網頁檔。私鑰、學校帳密、Wi-Fi 密碼及 GitHub token 不納入 repository。pi-station.pam 只留作舊版參考，新版不使用 PAM broker。

