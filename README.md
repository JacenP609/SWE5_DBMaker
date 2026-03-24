From here, it need below modifications 

해당 SourceCode 는 SWE.4 software Unit 의 Data Base 를 만들기 위한 Framework 이고, 이를 기반으로 SWE.5 software Uint 의 Frame work 를 만들어야함. 현제 환경은 가상환경으로 
현재 만들어지는 data 의 구성은 각 Entry 별 Component, Unit, Function, UI/CI (weather it is unit interface or Component Interface ). Risk, Function Body, Linked Work Items. 으로 구성되어있음. 

SWE.5 에서 필요한 Data 구성은 다음과 같음.

Component, Unit, Function, Caller Function ID , caller function body, target function body, Linked Work Items 으로 구성되어야함. 

우선 해당 data 처리를 위해서 주어지는 Input 을 살펴보면 
현 시점에 이미 존재하며, 동일하게 사용할 input : 
	Actual AM9C1 SourceCode 
	RAW_FOLDER 의 경로에 Component 별 Excel Raw 파일 
	component 명과 unit 명을 key 값으로 활용하는 code_path_map.json
	Raw 원본코드에서 build option 을 발라내기 위한 정보가 들어간 build_options.json

Target Function 의 Component 명과 Unit 명, Function명, 그리고 Target Function Body 는 기존 방식과 동일하게 수집한다. 
이외, Caller Function 의 Interface ID 와 Caller Function 의 function Body, Linked Work Items ( Target Function 의 ID ) 를 추가로 수집하여야 한다. 

Caller Function 의 functionBody 를 찾는 로직이 있어야 한다. 
처리하는 Target Function 의 Source/Destination 섹션에는 

예시) 
PowerManagement/NVMePowerManagementClient,
StartupTask/FormatStartupTask,
StartupTask/OpenStartupTask

다음과 같은 형식으로 Component/Unit 기준으로 해당 Function 의 Caller unit 위치가 정의 되어있다. 
이 중 내 Target Function 의 Component 가 아닌 외부 component 에서 호출되는 첫번째 위치를 찾는다. 
 **만일 모든 Caller Unit 이 동일 Component 에서 수행된다면, 해당 Function Entry 는 추가 처리하지않고 결과물도 스킵하고 다음 entry 로 넘어가야함**

해당 위치의 Component / Unit 명을 code_path_map.json 으로 탐색하여 caller Unit 의 위치를 찾는다. 
또한, 해당 Component 에 해당하는 RAW_FOLDER 의 excel 파일을 열어 Entry 의 Interface ID 를 기반으로 Caller Unit 의 Function 으로 정의된 Entry 들의 interface ID 와 Function 명을 수집한다. 
 **HIL_COMPONENT_UNIT_00 기준으로 Component 명 또는 Unit 명 사이에 _ 가 있을수 있어, Excel 명이 HIL_COMPONENT 인 점을 이용해 추출하는 기존 로직 참조**

이후 로직은 callerExtractor.py 라는 새로운 python 파일로 수행함. 
"""
CallerExtractor.py 의 내용 
Input : BuildOptionReaper.py 로 정리된 Caller Unit 의 전체 Code, Target Function 의 Caller Function name. 

Target Function을 부르는 Caller Function 을 찾는다.
caller Function 이 Private Function 일 경우, 해당 Private Function 을 부르는 Function 을 찾는다. 여러단계 Recursive 한 역산을 할 필요가 있음. 
Target Function 을 여러번 부를수도 있고, _private Function 이 여러번 불릴수도 있고 하지만, 전체적인 loop 를 다 돌 필요는 없다.
위 Caller Compoent Excel에서 수집한 InterfaceID, Function Pair 의 Function 이 Target Function 의 caller 로 찾아지면 해당 Pair 를 return 하며 Loop 는 종료된다. 
이후 Recursive 하게 확장된 전체 caller 의 Function Body 와, 해당 Function 의 Interface ID 를 반환한다. 

Output : Caller Function Body 와 Caller Function Interface ID.
"""

마지막으로 Linked Work Item 을 찾아줘야 한다. 이는 단순히 해당 Target Function 의 Function ID 를 찾아주는 것이다.**Interface ID 와 다름** 
