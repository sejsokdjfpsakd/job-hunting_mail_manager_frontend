# バックエンド API (rental_server) 本番環境デプロイガイド

さくらのレンタルサーバなどの、常時起動プロセスが許可されていない一般的なレンタルサーバーで動作させるためのガイドです。

## デプロイ手順

### 1. ファイルのアップロード
`rental_server` ディレクトリ内のファイルを、公開ディレクトリ（または非公開領域）にアップロードします。
同梱の `.htaccess` により、以下が設定されます：
- `.env` や `data/`、Python スクリプト (`*.py`) への直接アクセスのブロック
- CGI スクリプト (`api.cgi`) の実行許可
- API 認証に必要な `Authorization` ヘッダーの CGI への引き渡し
- ディレクトリ一覧表示 (Indexes) の無効化

### 2. 依存パッケージの準備
レンタルサーバー環境では `pip` や仮想環境が自由に扱えない場合が多いため、必要なパッケージをローカルで `packages` フォルダ内にインストールし、スクリプトと一緒にアップロードします。

ローカルでの準備例:
```bash
pip install -r requirements.txt -t packages/
```
> アップロード後、`api.cgi` の先頭部分で `sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'packages'))` のように記述し、パスが通るように設定します。

### 3. CGI スクリプトの設定
1. `api.cgi` のパーミッションを `755` (実行可能) に変更します。
2. `api.cgi` の先頭のシェバン（`#!/usr/bin/env python3` など）が、利用するレンタルサーバーの Python 3 のパスに合っているか確認・修正してください（例: `#!/usr/local/bin/python3`）。

### 4. 環境変数の設定 (.env の作成)
本番環境で動作させるには、必ず `.env` ファイルを作成する必要があります。
配布されている `.env.example` をコピーして `.env` を作成し、実際の接続情報を設定してください。

```bash
cp .env.example .env
```

`.env` 内の主な設定項目:
- `APP_BASE_URL`: 公開URL (例: `https://your-domain.sakura.ne.jp/mailmgr/`)
- `IMAP_HOST`: IMAPサーバーのホスト名 (例: `mail.your-domain.sakura.ne.jp`)
- `IMAP_PORT`: IMAPポート (`993` 推奨)
- `IMAP_USER`: メールアドレス
- `IMAP_PASSWORD`: メールパスワード（またはアプリパスワード）
- `API_KEY`: 内部APIキー（32文字以上）
- `OAUTH_BRIDGE_SECRET`: mcp_server と共通のシークレットキー（32文字以上）

> **シークレットキーの生成**:
> `python manage.py gen-secrets` を実行すると、`API_KEY` および `OAUTH_BRIDGE_SECRET` に利用できる安全なランダム文字列を生成できます。

### 5. データディレクトリ
`data/` フォルダが作成され、実行ユーザーに書き込み権限が付与されていることを確認してください。ルール情報や実行状態がここに JSON 形式で保存されます。

