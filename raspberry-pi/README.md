# 樹莓派 Wi-Fi 優先切換

此目錄只存程式與 systemd 設定；Wi-Fi 密碼與 SSH 登入密碼不放進 repository。

樹莓派端的 `/etc/pi-station-wifi.json` 包含 `ssid`、`uuid`（NetworkManager 連線 UUID）及 `interface`（例如 `wlan0`）。Wi-Fi 密碼由樹莓派的 NetworkManager 管理。

- 熱點設定 `connection.autoconnect=yes`、`connection.autoconnect-priority=999`。
- 熱點不可用時，由 NetworkManager 選擇其他允許自動連線的已存網路。
- 已連其他網路時，timer 約每 20–45 秒檢查一次熱點，偵測到後主動切換；切換時 SSH 會中斷。
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
