import argparse
import getpass
import os
import sys

from .config import ConfigError, invite_url, load_config, save_token, saved_token


def setup():
    if not sys.stdin.isatty():
        raise ConfigError('請在 Pi 的互動終端機執行 dc obf --setup。')
    os.umask(0o077)
    existing = saved_token()
    print('設定 OBF。token 隱藏輸入；直接 Enter 可沿用已保存的 token。')
    token = getpass.getpass('token: ') or existing
    configuration = save_token(token)
    print('設定已保存。要使用時執行 dc obf；現在已回到命令列。')
    print('首次使用請用這個連結邀請 bot：')
    print(invite_url(configuration['application_id']))


def main():
    parser = argparse.ArgumentParser(description='私人 Discord bot 按需啟動工具')
    sub = parser.add_subparsers(dest='bot', required=True)
    obf = sub.add_parser('obf', help='啟動 OBF，一份工作結束後退出；Ctrl+C 可取消。')
    mode = obf.add_mutually_exclusive_group()
    mode.add_argument('--setup', action='store_true', help='只設定 token，不啟動 bot。')
    mode.add_argument('--setupserver', action='store_true', help='建立 upload、processing、done 頻道模板，然後退出。')
    mode.add_argument('--status', action='store_true', help='顯示設定狀態，不連線 Discord。')
    mode.add_argument('--update', action='store_true', help='從 GitHub 抓取並測試新版；不啟動 bot。')
    # Phone keyboards sometimes replace the ASCII double dash with an em dash.
    args = parser.parse_args(['--' + s[1:] if s.startswith(('—', '–')) else s for s in sys.argv[1:]])
    try:
        if args.update:
            from .updater import update
            return update()
        elif args.setup:
            setup()
        elif args.setupserver:
            os.umask(0o077)
            from .server import setup_server
            return setup_server(load_config())
        elif args.status:
            configuration = load_config()
            print('token 已保存；按需啟動，未設定常駐服務。')
            print('VM 混淆引擎：' + ('已設定外部命令' if configuration.get('engine_argv') else '尚未接上'))
            print('三頻道模板：' + ('已設定' if configuration.get('server') else '未設定（dc obf --setupserver）'))
        else:
            os.umask(0o077)
            configuration = load_config()
            from .bot import run
            return run(configuration)
        return 0
    except KeyboardInterrupt:
        print('\n已結束。')
        return 130
    except (ConfigError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        # Do not render raw HTTP errors, tokens or uploaded code into the terminal.
        print(f'操作未完成（{type(error).__name__}）。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
