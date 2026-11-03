"""실행.bat / run.bat 이 부르는 시작 프로그램: API 키를 확인(없으면 물어서 .env 에 저장)한 뒤 편집기 화면을 엶."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HERE, ".env")


def get_key():
    from dotenv import set_key

    if os.environ.get("ANTHROPIC_API_KEY"):  # autocut 패키지가 .env 를 이미 읽어 둠
        return
    print()
    print("Claude API 키를 붙여넣고 Enter 를 누르세요. (sk-ant- 로 시작)")
    print("붙여넣기: 이 창에서 마우스 오른쪽 클릭")
    while True:
        key = input("키: ").strip()
        if key.startswith("sk-ant-"):
            break
        print("sk-ant- 로 시작하는 키가 아니에요. 다시 붙여넣어 주세요.")
    set_key(ENV_FILE, "ANTHROPIC_API_KEY", key, quote_mode="never")
    os.environ["ANTHROPIC_API_KEY"] = key
    print("키를 .env 파일에 저장했어요. 다음부터는 묻지 않아요.")


if __name__ == "__main__":
    os.chdir(HERE)
    sys.path.insert(0, HERE)
    import autocut  # noqa: F401  (.env 읽기)
    get_key()
    if not os.environ.get("OPENAI_API_KEY"):
        print("(OPENAI_API_KEY 가 없어서 설명 그림은 Claude 가 직접 그려요)")
    print()
    print("편집기를 여는 중이에요. 잠시 기다리면 인터넷 창이 열려요...")
    print("(이 창을 닫으면 편집기도 꺼져요)")
    from app import demo
    demo.queue().launch(inbrowser=True)
