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
1. `api.cgi.example` をコピーして `api.cgi` を作成します（`cp api.cgi.example api.cgi`）。
2. `api.cgi` の先頭のシェバン（`#!/usr/bin/env python3` など）が、利用するレンタルサーバーの Python 3 のパスに合っているか確認・修正してください（例: `#!/usr/local/bin/python3`）。
3. `api.cgi` のパーミッションを `755` (実行可能) に変更します。

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

### 6. 初回ログイン（パスキー登録）
本システムを利用するにはパスキーの登録が必要です。初回登録は以下のコマンドで発行される専用URLから行います。

```bash
python manage.py passkey-setup
```

実行後、コンソールに以下のようなURLが表示されます。

```text
以下のURLをブラウザで開いてパスキーを登録してください (15分間有効):
  https://your-domain.sakura.ne.jp/mailmgr/?setup=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

表示されたURLをブラウザで開き、「Register new Passkey」からPCやスマートフォンの認証（指紋・顔認証など）を登録してください。
※ セットアップURLは **15分間** のみ有効です。期限切れの場合はコマンドを再実行してください。

### 7. 定期実行 (cron) の設定
新着メールを自動で振り分ける（フォルダ分けする）ために、レンタルサーバーの cron 機能で `auto_label.py` を定期実行します。

#### 推奨実行頻度
- **10分〜15分おき**（例: `*/10 * * * *` または `*/15 * * * *`）
  > メールサーバーへの負荷や接続制限を避けるため、10〜15分間隔を推奨します。

#### 設定コマンド例

**さくらのレンタルサーバなど（WebコントロールパネルのCRON設定）**:
- **実行日時**: `*/15 * * * *` (15分ごと)
- **実行コマンド**:
  ```bash
  cd /home/<ユーザー名>/www/mailmgr && /usr/local/bin/python3 auto_label.py > /dev/null 2>&1
  ```
  ※ `<ユーザー名>` やディレクトリパスはご自身の環境に合わせて置き換えてください。
  ※ Python3 のパスはサーバー環境によって異なります（さくらのレンタルサーバ標準は `/usr/local/bin/python3`）。

**実行ログを記録したい場合**:
```bash
cd /home/<ユーザー名>/www/mailmgr && /usr/local/bin/python3 auto_label.py >> data/cron.log 2>&1
```

#### cron 実行に関する仕様・安全性
- **二重起動防止（排他制御）**: 前回の処理や Web UI / MCP からの手動実行が実行中の場合、重複実行せず自動的にスキップされます。
- **差分チェック**: 通常時は前回判定位置（UID）以降の新着メールのみを処理するため、高速かつ軽量に動作します。
- **タイムアウト対策**: サーバーの処理時間上限（既定25秒）に達した場合、自動的に安全に中断され、次回の cron 実行時に続きから再開されます。

