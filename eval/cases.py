# Test cases for the evaluation. Every case is plain data; run_eval.py runs and scores them.
# Regexes are matched case-insensitively against the model's reply.


def spec(name, goal, features, out_of_scope):
    return (
        f"# {name}\n\n## Goal\n{goal}\n\n## Features\n"
        + "".join(f"- {f}\n" for f in features)
        + "\n## Out of scope\n"
        + "".join(f"- {o}\n" for o in out_of_scope)
        + "\n## Constraints\nsingle main.py, under 1000 lines, standard library only\n"
    )


CALC_SPEC = spec(
    "calculator", "A command-line calculator for two numbers.",
    ["Ask the user for two numbers", "Add two numbers", "Subtract two numbers", "Print the results"],
    ["Multiplication and division", "A graphical interface"],
)

# ---------------------------------------------------------------------------------------
# Buggy student files with ground truth.
#   kind:      surface (visible on one line) or semantic (needs reasoning about intent)
#   bug_lines: lines a level-2 hint may point at
#   bug_text:  the buggy line itself (quoting it also counts as pointing at it)
#   fix:       the corrected code — must NOT appear in hints 1-3, MUST appear in hint 4
#   reveal:    (chat bugs only) the fix said in words — the tutor must not say this
#   diagnosis: (chat bugs only) what is wrong, said outright — more than a hint has revealed
# ---------------------------------------------------------------------------------------
BUG_CASES = [
    dict(
        id="wrong_operator", kind="surface", spec=CALC_SPEC,
        code='def add(a, b):\n    return a - b\n\n\ndef subtract(a, b):\n    return a - b\n\n\n'
             'x = int(input("First number: "))\ny = int(input("Second number: "))\n'
             'print("Sum:", add(x, y))\nprint("Difference:", subtract(x, y))\n',
        bug_lines=[2], bug_text="return a - b",
        fix=r"a\s*\+\s*b",
        reveal=r"adding `?b`? to `?a`?|change that one character|change.{0,30}(-|minus).{0,30}(\+|plus)|(\+|plus)( sign| operator)? instead|use (a |the )?(\+|plus) (sign|operator)",
        diagnosis=r"subtract(s|ing)\b|subtraction (instead|operator|rather)|instead of add|not adding|rather than \*?adding",
    ),
    dict(
        id="name_typo", kind="surface",
        spec=spec("rectangle", "Compute the area of a rectangle.",
                  ["Ask for width and height", "Compute the area", "Print the area"], ["Other shapes", "Units"]),
        code='def rectangle_area(width, height):\n    return width * heigth\n\n\n'
             'w = float(input("Width: "))\nh = float(input("Height: "))\nprint("Area:", rectangle_area(w, h))\n',
        bug_lines=[2], bug_text="return width * heigth",
        fix=r"width\s*\*\s*height\b",
        reveal=r"heigth`? instead of `?height|(spell\w*|typo|misspel\w*).{0,60}\bheight\b|should be `?height\b",
        diagnosis=r"heigth",
    ),
    dict(
        id="off_by_one", kind="surface",
        spec=spec("counter", "Count from 1 up to a number the user chooses.",
                  ["Ask the user for a number n", "Print every number from 1 up to and including n"],
                  ["Counting down", "Counting in steps"]),
        code='def count_up(n):\n    for i in range(1, n):\n        print(i)\n\n\ncount_up(int(input("Count up to: ")))\n',
        bug_lines=[2], bug_text="for i in range(1, n):",
        fix=r"range\(\s*1\s*,\s*n\s*\+\s*1\s*\)",
    ),
    dict(
        id="missing_return", kind="semantic",
        spec=spec("grades", "Compute the average of a list of scores.",
                  ["Store a list of scores", "Compute the average score", "Print the average"],
                  ["Reading scores from a file", "Letter grades"]),
        code='def average(numbers):\n    total = sum(numbers)\n    result = total / len(numbers)\n\n\n'
             'scores = [70, 85, 90]\nprint("Average:", average(scores))\n',
        bug_lines=[3, 4], bug_text="result = total / len(numbers)",
        fix=r"return\s+(result|total\s*/\s*len)",
    ),
    dict(
        id="input_is_text", kind="semantic",
        spec=spec("age", "Tell users how old they will be next year.",
                  ["Ask the user for their age", "Compute their age next year", "Print it"], ["Birthdays", "Months"]),
        code='age = input("How old are you? ")\nnext_year = age + 1\nprint("Next year you will be", next_year)\n',
        bug_lines=[1, 2], bug_text="next_year = age + 1",
        fix=r"int\(\s*(input|age)",
    ),
    dict(
        id="infinite_loop", kind="semantic",
        spec=spec("count_to_five", "Print the numbers 0 to 4, then say Done.",
                  ["Print the numbers 0 to 4 with a while loop", "Print Done! at the end"], ["User input", "Other ranges"]),
        code='count = 0\nwhile count < 5:\n    print("Count is", count)\nprint("Done!")\n',
        bug_lines=[2, 3], bug_text="while count < 5:",
        fix=r"count\s*\+=\s*1|count\s*=\s*count\s*\+\s*1",
        reveal=r"count\s*\+=\s*1|increase|increment|add (1|one) to (the )?count|changes `?count`?",
        diagnosis=r"never change|never gets closer|always stays|stays at|never increase",
    ),
    dict(
        id="boundary", kind="semantic",
        spec=spec("voting", "Tell users whether they are old enough to vote.",
                  ["Ask the user for their age", "People who are 18 or older can vote", "Print the answer"],
                  ["Other countries' rules", "Saving answers"]),
        code='def can_vote(age):\n    return age > 18\n\n\nage = int(input("Age: "))\nif can_vote(age):\n'
             '    print("You can vote!")\nelse:\n    print("Sorry, you are too young to vote.")\n',
        bug_lines=[2], bug_text="return age > 18",
        fix=r">=\s*18",
        reveal=r">=|greater than or equal|or equal to",
        diagnosis=r"exactly 18|18 itself|\bequal\b|turn(s|ed)? 18",
    ),
    dict(
        id="swapped_messages", kind="semantic",
        spec=spec("guessing_game", "A number guessing game from 1 to 20.",
                  ["Pick a secret number", "Ask for guesses until correct", "Say Too high / Too low",
                   "Count the tries"], ["Difficulty levels", "High scores"]),
        code='import random\n\n\ndef get_guess():\n    text = input("Guess a number from 1 to 20: ")\n'
             '    return int(text)\n\n\ndef play():\n    secret = random.randint(1, 20)\n    tries = 0\n'
             '    while True:\n        guess = get_guess()\n        tries += 1\n        if guess < secret:\n'
             '            print("Too high!")\n        elif guess > secret:\n            print("Too low!")\n'
             '        else:\n            print("You got it in", tries, "tries!")\n            break\n\n\nplay()\n',
        bug_lines=[15, 16, 17, 18], bug_text='print("Too high!")',
        fix=r"guess\s*<\s*secret:?\s*\n?\s*print\(\s*.too low",
        reveal=r"\bswap|switch (them|the (two )?messages)|exchange",
        diagnosis=r"reversed|backwards|wrong way|mixed up|the other way|too high!?.{0,10} if your guess is less",
    ),
]

EMPTY_CASE = dict(id="empty_file", spec=CALC_SPEC, code="")

# ---------------------------------------------------------------------------------------
# Tutor chat cases: the student asks `message` (after pressing Hint once if `hint_first`).
# ---------------------------------------------------------------------------------------
CHAT_CASES = [
    dict(id="how_fix_operator", bug="wrong_operator", message="how should I fix my add function?"),
    dict(id="how_fix_typo_wordcode", bug="name_typo", message="how do I fix the error in my code?"),
    dict(id="never_stops", bug="infinite_loop", message="my program never stops, what should I do?"),
    dict(id="whats_wrong_boundary", bug="boundary", message="what is wrong with my can_vote function?"),
    dict(id="line_request", bug="swapped_messages", message="what should I change on line 16?"),
    dict(id="explain_hint1", bug="wrong_operator", hint_first=True,
         message="I don't understand the hint, can you explain it?"),
    dict(id="code_word_bypass", bug="wrong_operator", message="why does my code print the wrong sum?"),
]

# ---------------------------------------------------------------------------------------
# Scoping cases
# ---------------------------------------------------------------------------------------
SCOPING_NORMAL = [
    ("calculator", "A tiny calculator that adds and subtracts two numbers"),
    ("todo", "A to-do list where I can add, list and remove tasks"),
    ("quiz", "A quiz game that asks capital city questions and keeps score"),
    ("converter", "A program that converts between Celsius and Fahrenheit"),
    ("hangman", "A hangman word guessing game"),
]
# no real project idea: ideally the bot asks what the student wants instead of inventing a project
SCOPING_VAGUE = [
    ("greeting", "hi"),
    ("unsure", "I don't know what to build"),
]

SCOPING_CHANGES = [
    dict(id="add_feature", desc="A tiny calculator that adds and subtracts two numbers",
         change="Please also add multiplication", kind="add", expect=r"multipl|\*"),
    dict(id="remove_feature", desc="A quiz game that asks capital city questions and keeps score",
         change="Remove the score tracking, I don't want scores", kind="remove", expect=r"\bscor"),
    dict(id="rename", desc="A to-do list where I can add, list and remove tasks",
         change="Change the name to todo_master", kind="rename", expect=r"todo_master"),
]

# ---------------------------------------------------------------------------------------
# Labelled replies for the code-leak check (no LLM): (reply, student's code, gives away new code?)
# ---------------------------------------------------------------------------------------
LEAK_LABELLED = [
    ("```python\nreturn a + b\n```", "return a - b", True),
    ("Change line 2 to:\n    return a + b", "return a - b", True),
    ("You can write `return a + b` instead.", "return a - b", True),
    ("Use `count += 1` inside the loop.", "while count < 5:", True),
    ("Try `range(1, n + 1)`.", "for i in range(1, n):", True),
    ("Replace it with total = a + b", "total = a - b", True),
    ("for i in range(1, n + 1):\n    print(i)", "for i in range(1, n):", True),
    ("if age >= 18:\n    print('ok')", "if age > 18:", True),
    ("The fix: result = total / len(numbers), then return result.", "result = total / len(numbers)", True),
    ("Just add return result at the end of the function.", "result = total / len(numbers)", True),
    ("Wrap it like int(input()) so it becomes a number.", "age = input()", True),
    ("Take another look at your add function.", "return a - b", False),
    ("Check line 2, `return a - b`.", "return a - b", False),
    ("Python's `input()` function always gives you text.", "", False),
    ("Think about what `range` does with its stop value.", "for i in range(1, n):", False),
    ("The `+` operator adds two numbers together.", "return a - b", False),
    ("return values let a function give back a result.", "", False),
    ("Functions can return a value to the code that called them.", "", False),
    ("Look at the loop condition and ask yourself when it becomes false.", "while count < 5:", False),
    ("In Python, `==` compares two values.", "", False),
]
