# 樹莓派 Wi-Fi 優先切換

此目錄只存程式與 systemd 設定；Wi-Fi 密碼與 SSH 登入密碼不放進 repository。

樹莓派端的 `/etc/pi-station-wifi.json` 包含 `ssid`、`uuid`（NetworkManager 連線 UUID）及 `interface`（例如 `wlan0`）。Wi-Fi 密碼由樹莓派的 NetworkManager 管理。

- 熱點設定 `connection.autoconnect=yes`、`connection.autoconnect-priority=999`。
- 熱點不可用時，由 NetworkManager 選擇其他允許自動連線的已存網路。
- 已連其他網路時，timer 約每 20–45 秒檢查一次熱點，偵測到後主動切換；切換時 SSH 會中斷。
- 使用 NetworkManager 的 `LastSeen` 確認熱點在最近 15 秒內被掃到，避免已關閉的熱點仍留在掃描快取而觸發切換。
- 熱點驗證失敗會嘗試恢復前一個網路，並等待 3 分鐘再試，避免持續中斷備用網路。
- 停用 Wi-Fi 無線電時不會強制重新啟用。

安裝位置：`/usr/local/lib/pi-station/prefer-hotspot.py`、`/etc/systemd/system/pi-station-wifi.service`、`/etc/systemd/system/pi-station-wifi.timer`。安裝後需 `sudo systemctl daemon-reload` 與 `sudo systemctl enable --now pi-station-wifi.timer`。

查狀態：

```sh
systemctl status pi-station-wifi.timer
journalctl -u pi-station-wifi.service -n 20 --no-pager
nmcli -f NAME,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show
```

暫停主動切換：`sudo systemctl disable --now pi-station-wifi.timer`。若服務正在嘗試連線，也可 `sudo systemctl stop pi-station-wifi.service`。停用 timer 後，NetworkManager 仍保留熱點優先級。

NetworkManager 官方說明：[連線優先級與自動連線](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nm-settings-nmcli.html)。優先級本身不會取代已啟用的網路，因此另用 timer 偵測熱點。

## HTTPS 與登入服務

`pi-station-device.service` 與 `pi-station-auth.service` 皆開機啟動。

| 檔案 | 正式位置 |
| --- | --- |
| `device-server.py`, `auth-server.py` | `/usr/local/lib/pi-station/`（root 擁有，644） |
| `pi-station-device.service`, `pi-station-auth.service` | `/etc/systemd/system/` |
| `pi-station.pam` | `/etc/pam.d/pi-station` |
| 網頁三個檔案 | `/opt/pi-station/web/`（root 擁有，644） |
| TLS 公開憑證 | `/etc/pi-station/server.crt`（644） |
| TLS 私鑰 | `/etc/pi-station/server.key`（root 擁有，600；不公開、不入版控） |
| PAM broker socket | `/run/pi-station-auth/auth.sock`（root:sean，660） |

systemd 的 `LoadCredential` 將私鑰提供給網頁服務，網頁帳號無法直接讀取原始 root 私鑰。TLS 最低版本 1.2。自簽憑證包含 `sean.local`、`sean`、`127.0.0.1`、目前家用 IP 與既知 iPhone 熱點小網段；更換網路而使用其他 IP 時須重新簽發包含該位址的憑證並重新核對指紋。

更新時先在 root 專用目錄備份現有檔案，再安裝程式、unit、PAM 設定與網頁，驗證語法後執行：

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now pi-station-auth.service
sudo systemctl restart pi-station-device.service
systemctl is-active pi-station-device.service pi-station-auth.service
```

`/api/v1/discovery` 可在 HTTP 或 HTTPS 存取，僅回傳公開固定識別；狀態與未來的操作 API 需要 HTTPS、session 及適用的 CSRF 檢查。登入用系統 `sean` 的原密碼，不另外建立網頁明文密碼。

核對憑證：

```sh
sudo openssl x509 -in /etc/pi-station/server.crt -noout -fingerprint -sha256 -enddate
```

更換密碼由本人透過系統操作完成。本控制台不提供更改密碼功能。
