"""실행.bat 이 부르는 시작 프로그램: API 키를 확인(없으면 물어서 저장)한 뒤 편집기 화면을 엶."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(HERE, "api_key.txt")


def get_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, encoding="utf-8") as f:
            key = f.read().strip()
        if key.startswith("sk-ant-"):
            os.environ["ANTHROPIC_API_KEY"] = key
            return
    print()
    print("Claude API 키를 붙여넣고 Enter 를 누르세요. (sk-ant- 로 시작)")
    print("붙여넣기: 이 창에서 마우스 오른쪽 클릭")
    while True:
        key = input("키: ").strip()
        if key.startswith("sk-ant-"):
            break
        print("sk-ant- 로 시작하는 키가 아니에요. 다시 붙여넣어 주세요.")
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    os.environ["ANTHROPIC_API_KEY"] = key
    print("키를 저장했어요. 다음부터는 묻지 않아요.")


if __name__ == "__main__":
    os.chdir(HERE)
    sys.path.insert(0, HERE)
    get_key()
    print()
    print("편집기를 여는 중이에요. 잠시 기다리면 인터넷 창이 열려요...")
    print("(이 창을 닫으면 편집기도 꺼져요)")
    from app import demo
    demo.queue().launch(inbrowser=True)
