# DC OBF

樹莓派上的按需、單次 Discord Lua VM 混淆 bot。私人伺服器操作，
不設定常駐服務或開機啟動；處理一份有效工作後退出，Ctrl+C 也可取消。

## 操作

```sh
dc obf --setup
```

只詢問 `token:`，隱藏輸入。讀取 Discord 應用程式資料驗證 token，
自動取得擁有者 ID，儲存在 `~/.config/dc/obf.json`（0600），然後返回
命令列，不啟動 bot。首次使用依畫面邀請連結加入自己的私人伺服器。
不要把 token 放入 GitHub、聊天或命令參數。

```sh
dc obf
```

Bot 上線後，在 Discord 使用 `/obf`，附件欄位 `file` 選 `.lua`。
同一則嵌入訊息顯示收檔、檢查、VM 處理、完成／失敗與耗時。
引擎未提供內部百分比，因此不顯示假百分比。完成後回傳
`protected.lua` 並下線；格式錯誤的附件可重新選取。

`/obf_status` 可查看本次狀態。來源會經過 Discord；這不是純本機傳檔。
目前限 app 擁有者使用，來源限制 2 MiB，處理逾時 120 秒，輸出限制
8 MiB 且不超過本次 interaction 的附件上限。worker 不直接執行上傳原碼。

```sh
dc obf --status
dc obf --update
```

`--status` 只查本機設定。`--update` 從
[0xseanlee/pi](https://github.com/0xseanlee/pi) 的 main 分支抓 `dc-obf/`。
repo 是公開的，Pi 抓取不需要 GitHub token。

更新版本保存在 `~/.local/share/dc-obf/releases/<commit>/`：先在獨立
venv 安裝、測試，通過才原子切換 `current`。失敗保留舊版，前版記在
`previous`。更新不會啟動 bot，也不覆寫 Discord token。更新途中斷線
或斷電，不會啟用沒有 `.ready` 標記的版本；重新執行 update 可重試。
執行中的 bot 與更新互斥。首次 bootstrap 使用 `~/dc-tools`。

套件依賴會依 Python 平台與 pyproject 需求保存成有 SHA-256 校驗的
本機 wheel 快取。首次準備快取仍需連上 PyPI；之後依賴不變時，
建置與安裝使用 `--no-index`，不重查套件站。下載僅針對此更新程序
使用官方 PyPI，保留 TLS 驗證、憑證與代理設定，不更改系統 pip 設定。

若看到反覆 `SSLEOFError`／`RemoteDisconnected`，可以 Ctrl+C 停止
更新，原本已啟用版本仍在。可先執行 `dc obf --setup` 和 `dc obf`，
等網路穩定再更新。注意舊 updater 首次升到這個版本時，仍使用舊的
安裝路徑；需至少一次完成升級，新的依賴快取機制才會生效。

穩定入口是 `~/dc-tools/bin/dc`，系統短指令 `/usr/local/bin/dc`
指向它；入口選擇已測試的新版本或原本 bootstrap。

## 後端與驗證範圍

第一版採用固定版本 Prometheus Medium 的 VM 管線，輸出目標為 LuaU。
這不是自製 VM，也不宣稱完整支援所有 Luau 語法或注入器 API。
使用者尚未指定注入器與真實腳本，相容性仍需自行執行確認。

Based on Prometheus by Elias Oelschner, https://github.com/prometheus-lua/Prometheus

後端版本：`a98c50165f2a53f6d765a82eee60dfea53803445`。
版本隔離儲存在 `~/.local/lib/dc-obf/backends/`，保留上游 LICENSE。
[上游授權](https://github.com/prometheus-lua/Prometheus/blob/a98c50165f2a53f6d765a82eee60dfea53803445/LICENSE)。

測試涵蓋私人 token 設定、附件指令、進度嵌入、單次退出、worker
逾時、拒絕原樣回傳、更新原子切換與鎖，以及自有安全 fixture 的
混淆前後行為比較。測試不使用真實 Discord token 或上傳私人腳本。

```sh
python -m unittest discover -s tests -v
```

Discord 真實登入、指令註冊、收檔回檔仍待使用者執行 setup 及開啟 bot。
完整研究背景：[research.md](research.md)。
