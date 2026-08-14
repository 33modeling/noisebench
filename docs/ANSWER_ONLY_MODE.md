# 답변 전용 노이즈 모드

`answer_only` 모드는 질문, 문맥, instruction, 코드 prompt를 그대로 유지하고
정답 또는 모델 응답에만 노이즈를 넣는다. 데이터 생성이 끝난 뒤 모든 `input`과
전체 행 수가 원본과 같은지 다시 검사하며, 검사를 통과하지 못하면 결과를 저장하지
않고 실행을 실패시킨다.

## CLI 사용

MBPP 정답 코드의 10%에 단어 삭제 노이즈를 적용한다.

```bash
cd /home/kms/noisebench

.venv/bin/noisebench inject \
  --input data/normalized/mbpp/train.jsonl \
  --operator random_deletion \
  --rate 0.10 \
  --param 'alpha=0.15' \
  --answer-only \
  --seed 42 \
  --output-dir data/generated/mbpp-answer-delete-r10-s42
```

이 명령에서 `input.prompt`는 바뀌지 않고 `target.code`만 변경된다.

## 설정 파일 사용

```json
{
  "input": "data/normalized/tydiqa/train.jsonl",
  "seed": 42,
  "answer_only": true,
  "output_dir": "data/generated/tydiqa-answer-only-s42",
  "operations": [
    {"name": "random_swap", "rate": 0.10, "alpha": 0.15},
    {"name": "response_swap", "rate": 0.10},
    {"name": "truncate_response", "rate": 0.10, "keep_fraction": 0.5}
  ]
}
```

실행:

```bash
.venv/bin/noisebench inject --config configs/examples/mbpp_answer_only.json
```

## 허용되는 연산자

| 연산자 | 답변 전용 동작 |
|---|---|
| `symmetric_label_flip` | 객관식 정답 라벨만 변경 |
| `asymmetric_label_flip` | 전이 규칙에 따라 객관식 정답 라벨만 변경 |
| `response_swap` | 다른 샘플의 target만 복사 |
| `wrong_answer` | 객관식 오답 또는 다른 target으로 변경 |
| `truncate_response` | 답변 또는 코드 target만 절단 |
| `random_deletion` | 답변 문자열의 단어만 삭제 |
| `random_swap` | 답변 문자열의 단어 순서만 변경 |
| `synonym_replacement` | 답변 문자열의 단어만 동의어로 교체 |
| `random_insertion` | 답변 문자열에만 동의어 삽입 |

텍스트 연산자에는 내부적으로 `scope: "response"`가 자동 설정된다. 개별 연산만
답변에 적용하려면 전체 `answer_only` 대신 연산자에 직접 다음처럼 지정할 수도 있다.

```json
{
  "name": "random_deletion",
  "rate": 0.10,
  "alpha": 0.15,
  "scope": "response"
}
```

## 차단되는 연산자

- `trigger_backdoor`: trigger를 질문이나 prompt에 추가하므로 차단한다.
- `exact_duplicate`: 행 수를 변경하므로 차단한다.
- `near_duplicate`: 행 수와 입력을 변경하므로 차단한다.

`answer_only: true`에서 위 연산자를 사용하거나 `input.question` 같은 입력 필드를
직접 지정하면 오류가 발생한다. 설정을 무시하거나 입력까지 변경한 채 계속 진행하지
않는다.

## Manifest 확인

성공한 실행의 `manifest.json`에는 다음 검증 결과가 기록된다.

```json
{
  "answer_only": true,
  "answer_only_verification": {
    "input_unchanged": true,
    "row_count_unchanged": true
  }
}
```

텍스트 연산자 이벤트에도 `"scope": "response"`가 기록되므로 레코드별로 답변
전용 적용 여부를 확인할 수 있다.
