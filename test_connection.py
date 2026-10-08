import imaplib
import socket
from config import get_settings

def test_imap_connection():
    settings = get_settings()

    print("--- 読み込まれた設定 ---")
    print(f"IMAP_HOST: {settings.imap_host}")
    print(f"IMAP_PORT: {settings.imap_port}")
    print(f"IMAP_USER: {settings.imap_user}")
    print(f"IMAP_MOCK: {settings.imap_mock}")
    print("------------------------\n")

    if settings.imap_mock:
        print("現在は IMAP_MOCK=1 が設定されており、モック（ダミー）モードです。")
        print("本番のサーバーに接続するには .env の IMAP_MOCK=1 を削除またはコメントアウトし、")
        print("IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASSWORD を設定してください。")
        return

    if not settings.imap_host or not settings.imap_user:
        print("エラー: .env ファイルに IMAP_HOST と IMAP_USER が設定されていません。")
        return

    print(f"[{settings.imap_host}:{settings.imap_port}] へ接続を試みます...")

    try:
        if settings.imap_port == 993:
            mail = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
        else:
            mail = imaplib.IMAP4(settings.imap_host, settings.imap_port)
        
        print("接続成功。ログインを試みます...")
        mail.login(settings.imap_user, settings.imap_password)
        
        print("✅ ログインに成功しました！メールサーバーの情報は正しく設定されています。")
        mail.logout()
        
    except imaplib.IMAP4.error as e:
        print(f"❌ ログインに失敗しました（認証エラー）: {e}")
    except socket.gaierror:
        print("❌ ホスト名が見つかりません。IMAP_HOST が正しいか確認してください。")
    except ConnectionRefusedError:
        print("❌ 接続が拒否されました。ポート番号（IMAP_PORT）やサーバー設定が正しいか確認してください。")
    except Exception as e:
        print(f"❌ 予期せぬエラーが発生しました: {e}")

if __name__ == '__main__':
    test_imap_connection()
