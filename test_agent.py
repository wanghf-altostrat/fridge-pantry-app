import asyncio
from google.adk.runners import InMemoryRunner
from google.genai import types
from app.agent import app

async def main():
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name="app", user_id="test_user"
    )
    print(f"Session created: {session.id}\n")

    # Turn 1: Check fridge & pantry
    print("--- TURN 1: Initial run ---")
    user_msg1 = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Check my fridge and pantry, flag expiring foods, and suggest recipes.")]
    )
    
    async for event in runner.run_async(
        user_id="test_user",
        session_id=session.id,
        new_message=user_msg1,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(f"[Content]\n{part.text}\n")
                elif part.function_call:
                    print(f"[HITL RequestInput Call] {part.function_call.name}: {part.function_call.args.get('message')}\n")

    # Turn 2: User responds selecting recipe 1 ("Chicken & Tomato Skillet")
    print("--- TURN 2: User responds 'I choose recipe 1 (Chicken & Tomato Skillet)' ---")
    user_msg2 = types.Content(
        role="user",
        parts=[types.Part.from_text(text="I choose recipe 1")]
    )
    async for event in runner.run_async(
        user_id="test_user",
        session_id=session.id,
        new_message=user_msg2,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(f"[Content]\n{part.text}\n")

if __name__ == "__main__":
    asyncio.run(main())
