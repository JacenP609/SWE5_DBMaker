# SWE5 DBMaker

이 스크립트는 **SWE.5 데이터 생성**을 위해, 각 Target Function에 대해 아래 정보를 만듭니다.

- Component
- Unit
- Function
- Caller Function ID
- Caller Function Body
- Target Function Body
- Linked Work Items (SWE.2 Function ID)

---

## 핵심 시나리오

예시 Entry:

- Target: `Component/UNIT/Initialize`
- Source/Destination: `CoreComponent/CoreUnit`

처리 흐름은 아래와 같습니다.

1. **Target 식별**
   - Raw Excel의 `Interface ID`, `Interface Name`으로 Target `Component/Unit/Function`을 얻습니다.

2. **외부 Caller Unit 결정**
   - `Source/Destination`에서 Target Component와 다른 첫 번째 `Component/Unit`을 Caller 위치로 선택합니다.
   - 모두 같은 Component면 SWE.5 범위 밖으로 보고 skip 합니다.

3. **Caller Interface 후보 수집**
   - Caller Component의 Raw Excel에서 Caller Unit에 해당하는 Interface pair(`Interface ID`, `Interface Name`)를 모읍니다.

4. **Caller 코드에서 역추적(BFS)**
   - Caller Unit 코드(.h/.cpp, build option 반영)에서
     `Target Function`을 호출하는 함수들을 역방향으로 탐색합니다.
   - 탐색 중 Interface 후보 함수를 만나면 그 함수를 Caller Interface로 확정합니다.

5. **Body 추출**
   - Target Function Body 추출
   - Caller Function Body 추출
   - 확장은 로컬 함수 위주로 제한하여 성능/오탐을 줄입니다.

6. **Linked Work Item 연결**
   - SWE2_WorkItem의 Title(`{unit} {function}`) 기준으로 Function ID를 찾고,
   - 중복 시 `sources.json` + `has parent(s):` 정보를 이용해 Component를 좁혀 결정합니다.

7. **결과 저장**
   - 최종 결과를 Component/Unit 단위 엑셀로 `Results/` 아래에 저장합니다.

---

## 입력

- FW Source Code
- `RAW_FOLDER` 내 Component별 Raw Excel
- `code_path_map.json` (component/unit -> code path)
- `build_options.json` (Build option 필터링)
- `SWE2_WorkItem.xlsx`
- `sources.json`

---

## 출력

- `Results/<Component>/<Component>_<Unit>.xlsx`
- `log/` 하위 진단 로그

---

## 운영 메모

- 처리 중 콘솔에는 Component 시작/종료 및 row 단위 진행률/시간이 출력됩니다.
- caller/target body 확장 깊이는 `main.py` 설정값으로 조정할 수 있습니다.
