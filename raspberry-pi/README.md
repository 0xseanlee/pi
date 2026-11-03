# 樹莓派服務

功能、安裝及還原方式請見[主 README](../README.md)。

- 原有熱點切回與 HSSH 登入機制保持原樣。
- auth-server.py 只接受本機 sean UID 請求，用 loopback SSH 驗證帳密並固定本機主機金鑰。
- device-server.py 提供 HTTPS、session 與 CSRF；control.py 實作控制 API。
- install-console.sh 負責雜湊校驗、備份、更新與失敗還原。

