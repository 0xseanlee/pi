# DC OBF

樹莓派上的按需、單次 Discord Lua VM 混淆 bot。私人伺服器操作，
執行 `dc obf` 即在背景等候，可關閉 SSH。處理一份有效工作後退出，
也可用 `dc obf --close` 停止；不設定開機自動啟動。

## 操作

```sh
dc obf --setup
```

只詢問 `token:`，隱藏輸入。讀取 Discord 應用程式資料驗證 token，
自動取得擁有者 ID，儲存在 `~/.config/dc/obf.json`（0600），然後返回
命令列，不啟動 bot。首次使用依畫面邀請連結加入自己的私人伺服器。
不要把 token 放入 GitHub、聊天或命令參數。

```sh
dc obf --setupserver
```

在 bot 所在的私人伺服器建立 `dc-obf` 分類及三個文字頻道；多個伺服器
時會列出名稱與 ID 供選擇。需要你是伺服器擁有者或有「管理伺服器」
權限；bot 需要「管理頻道」及讀寫、嵌入、附件權限，缺少時會顯示
重新授權連結。分類預設只允許你與 bot 檢視（管理員仍可檢視）。
再次執行沿用工具建立的頻道，不刪除紀錄、不改動其他同名頻道。
設定完成即退出；這個指令也接受手機鍵盤的 `—setupserver`。

| 頻道 | 用途 |
| --- | --- |
| `upload` | 使用 `/obf`，在 `file` 選 `.lua` 或 `.lua.txt`；bot 另貼原始檔備份 |
| `processing` | 每份工作一則進度嵌入，顯示階段、耗時與工作 ID |
| `done` | 保留 `protected.lua` 與完成紀錄，失敗也留下紀錄 |

```sh
dc obf
```

執行後會返回命令列，bot 以獨立 session 在背景連線／等待；關閉 iSH 或
SSH 不會因終端機掛斷而停止 bot。不用額外加 `&`、nohup 或維持視窗。
畫面會區分「背景連線中」與「已上線」，前者不是已驗證 Discord 登入。
重複執行 `dc obf` 不會重複啟動；`dc obf --status` 可查本機控制端狀態。
記錄保存在 `~/.local/state/dc-obf/bot.log`（0600），不寫入 repo。

重新 SSH 到同一台 Pi、同一個 `sean` 帳號，可隨時停止：

```sh
dc obf --close
```

手機輸入的 `dc obf —close` 也接受。會中止目前混淆程序，保存已接收的
檔案並記錄取消，再讓 bot 下線；不刪除 token、頻道或歷史紀錄。
已下線時重複執行只顯示已關閉。控制走本機私人 Unix socket，不靠
程序名稱或過期 PID 殺程序，也不關閉其他 bot、更新或模板設定。
需要留在前景除錯時可用 `dc obf --foreground`，在該視窗 Ctrl+C 取消。
首次升級前已啟動的舊版沒有控制端，需先 Ctrl+C
再 `dc obf --update`，用新版啟動後才能透過 `--close` 停止。

要使用時才啟動，完成一份有效工作即下線。不是直接丟檔案就自動處理，
請在 `upload` 使用 `/obf`。Safari 把 Lua 下載成 `.lua.txt` 也接受，
會與 `.lua` 一樣檢查 UTF-8、大小和內容，原始檔名記在工作紀錄中。
一般 `.txt` 不會自動當成 Lua。無須 Message Content Intent；來源會經過
Discord。未套模板時仍可在原頻道使用 `/obf`，回覆原則與以往相同。
`/obf_status` 查看本次狀態。進度依實際階段更新，引擎沒有內部百分比。

每份已接收工作在 Pi 的 `~/.local/share/dc-obf/jobs/<工作ID>/` 保存
`input.lua`、成功產生的 `protected.lua` 和 `job.json`（時間、SHA-256、
狀態、Discord 訊息連結）。目錄 0700、檔案 0600，與 release 分開；
更新不清除紀錄，失敗與取消也保留已保存的內容，不自動到期刪除。
超出引擎處理上限而遭拒絕的附件不會下載或備份。Pi 本機儲存空間
用盡會停止工作，並非無限容量；Discord 訊息被刪除也不影響 Pi 副本。
不要把 Discord CDN 暫時下載網址當成永久檔案索引。

## Discord 上限與引擎上限

截至 2026-11-11 查閱的 [Discord 檔案 FAQ](https://support.discord.com/hc/en-us/articles/25444343291031-File-Attachments-FAQ)：
免費 20 MB、Nitro Basic 50 MB、Nitro 完整版最高 1 GB／檔；部分帳號
有實驗限制，以客戶端實際顯示為準。官方部分舊頁仍列 Nitro 500 MB。

[API 文件](https://docs.discord.com/developers/reference#uploading-files)
目前列預設 20 MiB／檔；一般 bot 頻道上傳受伺服器額度限制，
[Boost Level 2 / 3](https://support.discord.com/hc/en-us/articles/360028038352-Server-Boosting-FAQ)
分別提供 50 / 100 MB，部分伺服器另有 250 MB 實驗加成。
Slash 回覆使用 Discord 回傳的 `attachment_size_limit`，可能與一般
bot 發訊息不同；你的個人 Nitro 不會讓所有 bot 頻道訊息自動享有 1 GB。

**本工具目前另有限制：原檔 2 MiB、輸出 8 MiB、處理逾時 120 秒。**
這是 Pi VM 引擎的處理限制，並非宣稱可處理 1 GB Lua。三頻道模式
回檔採 `guild.filesize_limit`，原頻道模式採 `interaction.filesize_limit`；
目前固定的 discord.py 2.7.1 對普通 guild 的預設仍保守列為 10 MiB。
不硬編碼保證所有上下文均可達 20 MiB，實際傳送失敗仍保存 Pi 產物。
worker 只解析／轉換，不直接執行上傳原碼。

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

測試涵蓋私人 token 設定、頻道模板重跑及中斷恢復、原檔及產物保存、
背景啟動、原啟動 session 收到 SIGHUP 後仍存活、不重複啟動、私人記錄、
Discord 傳送失敗後保留檔案、跨程序 close 中止真實 worker 並保存取消
紀錄、附件指令、進度嵌入、單次退出、worker
逾時、拒絕原樣回傳、更新原子切換與鎖，以及自有安全 fixture 的
混淆前後行為比較。測試不使用真實 Discord token 或上傳私人腳本。

```sh
python -m unittest discover -s tests -v
```

Discord 真實登入、套頻道模板、指令註冊、收檔回檔仍待使用者執行。
本次變更在 Mac 驗證，尚未部署至離家的 Pi；請先完成 `dc obf --update`。
完整研究背景：[research.md](research.md)。
