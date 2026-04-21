# Calendar Error Handling

Naver CalDAV 연동 실패는 아래 분류를 기준으로 해석한다.

## Error Categories

- `configuration`
  - 예: 누락된 환경 변수, 잘못된 timeout/cache 설정값
  - 자동 재시도하지 않는다
  - 수동 조치가 필요하다

- `validation`
  - 예: 잘못된 CLI 날짜 입력값
  - 자동 재시도하지 않는다
  - 입력 수정 후 다시 실행한다

- `authentication`
  - 예: 401, 403, unauthorized, forbidden
  - 자동 재시도하지 않는다
  - 앱 비밀번호/계정 설정을 수동 확인한다

- `network`
  - 예: timeout, connection reset, DNS 실패, connection refused
  - backoff 재시도 대상이다
  - 반복 실패 시 알림 대상으로 승격할 수 있다

- `query`
  - 예: 일시적 provider 오류, 조회 중 일반 요청 실패
  - 원인에 따라 backoff 재시도 가능하다
  - 반복 실패 시 수동 점검 또는 알림 대상으로 승격한다

- `parsing`
  - 예: CalDAV payload 추출 실패, 일정 파싱 실패
  - 기본적으로 자동 재시도하지 않는다
  - 원본 데이터 점검이 필요하다

- `dependency`
  - 예: `caldav`, `icalendar` 패키지 누락
  - 자동 재시도하지 않는다
  - 실행 환경을 수동으로 복구한다

- `unknown`
  - 명확한 분류가 어려운 실패
  - 제한된 backoff 재시도 후 알림 대상으로 본다

## Retry Strategy

- `none`
  - 자동 재시도를 수행하지 않는다

- `backoff`
  - 짧은 지연을 두고 재시도한다
  - 권장 재시도 횟수는 에러 payload의 `recommended_retry_count`를 따른다

## Alerting Guidance

- `alert_recommended=true`
  - Discord, 로그 집계, 운영 알림 채널에 연결하기 좋은 실패

- `alert_recommended=false`
  - 단기 재시도 또는 사용자 입력 수정으로 해결 가능한 실패

## Payload Contract

`yule calendar events --json` 실패 응답은 아래 필드를 포함한다.

- `error.code`
- `error.category`
- `error.message`
- `error.retryable`
- `error.retry_strategy`
- `error.recommended_retry_count`
- `error.manual_action_required`
- `error.alert_recommended`
- `error.recovery_hint`
- `error.raw_message`

Planning Agent, Discord 브리핑, 자동 재시도 로직은 위 payload를 그대로 재사용한다.
