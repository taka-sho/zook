# アーキテクチャパターン集

要件からYAMLをゼロに組み立てるより、ここにある近いパターンを土台にして差分を編集するほうが、構造の破綻なく安定して構成図を作れます。まずこのページで要件に近いパターンを選び、そのYAMLを読み込んで、要件に合わせてノードの追加・削除・ラベル変更を行ってください。全パターンは `archdiagram validate` で警告ゼロを確認済みです。

型(コンピューティングの実行方式)を変えずに要件だけ変わる場合は、パターン内のラベルや個数を差し替えるだけで済みます。型そのものが要件に合わない場合(例:サーバー管理をしたくないのにEC2ベースのパターンを選んでしまった)は、別のパターンに乗り換えてください。

## `3tier-web-app.yaml` — 王道の3層Webアプリ

ALB配下に複数AZのEC2 Webサーバーを並べ、各AZにRDSを置いた冗長構成です。「Webアプリを新しく作りたい」「特別な要件がなければ実績のある構成にしたい」という依頼にまず当てはめてください。サーバーの起動・停止やOSパッチ適用を自前で管理する前提の構成なので、運用負荷を下げたい要件には次の `serverless-api.yaml` や `container-platform.yaml` のほうが適します。

## `serverless-api.yaml` — サーバー管理をしたくないAPI

API GatewayでHTTPSリクエストを受け、Lambdaで処理し、DynamoDBに永続化します。認証はCognitoです。「サーバーの管理をしたくない」「トラフィックが不定期・低頻度」「まず小さく作って伸ばしたい」という要件に向きます。常時起動のコンテナやVMを好まない場合の第一候補です。

## `event-driven-processing.yaml` — 非同期・疎結合な処理

S3へのアップロードをEventBridgeで検知し、SQSでバッファしてからLambdaが処理する構成です。処理完了はSNSで通知します。「同期応答が不要」「後続処理が詰まっても受付側を止めたくない」「複数の消費者に同じイベントを配りたい」という要件に選んでください。リクエスト直後に結果を返す必要がある要件には向きません。

## `container-platform.yaml` — コンテナのまま動かしたい基盤

ALB配下でECS(Fargate)がアプリケーションを実行し、Auroraに永続化、ElastiCacheでセッションをキャッシュします。「Dockerイメージが既にある」「サーバー管理は減らしたいが、コンテナという単位のまま動かしたい」という要件に合います。関数単位の細かい従量課金より、常時稼働のサービスとして動かしたい場合はこちらを選んでください。

## `static-site-cdn.yaml` — 静的サイト・SPAの配信

Route53でドメインを解決し、CloudFront経由でS3の静的ファイルを配信します。「バックエンド処理を持たない、あるいは別途APIとして分離する」「静的サイトやSPAを配信したい」という要件に向きます。動的なサーバー処理が要件に含まれる場合は、`serverless-api.yaml` と組み合わせてください。

## `gcp-serverless-api.yaml` — GCP版のサーバーレスAPI

`serverless-api.yaml` のGCP版です。API GatewayでHTTPSリクエストを受け、Cloud Functionsで処理し、Firestoreに永続化します。認証はIdentity Platformです。要件でGCPが明示されているときに選んでください。

## `azure-container-app.yaml` — Azure版のコンテナ基盤

`container-platform.yaml` のAzure版です。Front DoorでHTTPSを受け、Container Appsでアプリを実行し、Cosmos DBに永続化します。認証はEntra IDです。要件でAzureが明示されているときに選んでください。

## パターンの選び方

要件文からまず次の2点を読み取ってください。

1. **クラウドプロバイダの指定があるか。** 明示が無ければAWS版から選び、GCP/Azureの指定があれば対応するGCP/Azure版を選びます(GCP/Azure版は現状 `serverless-api.yaml`/`container-platform.yaml` の2系統のみ用意しています)。
2. **コンピューティングの実行方式に希望があるか。** サーバー管理を避けたいなら `serverless-api.yaml`、Dockerイメージ前提でコンテナのまま動かしたいなら `container-platform.yaml`、特別な指定が無ければ `3tier-web-app.yaml`、非同期・イベント駆動が明示されていれば `event-driven-processing.yaml`、配信対象が静的コンテンツのみなら `static-site-cdn.yaml` を選びます。

どのパターンにも当てはまらない要件は、複数パターンを組み合わせるか(例:静的サイト配信 + サーバーレスAPI)、`docs/yaml-spec.md` と `archdiagram icons list` を参照しながら新規に組み立ててください。使えるサービス名は `docs/icon-registry-and-vocabulary.md` の通りTier-1語彙(AWS26・GCP19・Azure18サービス)に限られるので、それ以外のサービスが要件に含まれる場合は、近い代替サービスに読み替えるか、ユーザーに確認してください。
