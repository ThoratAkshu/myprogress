"""The code lab: walkthroughs to watch run step by step. Code runs only in the person's browser (Python with Pyodide,
JavaScript in a sandboxed frame). Problems to solve with tests are in problems.py."""

RUNNABLE = {"python": "Python", "javascript": "JavaScript"}


def walkthrough(key, language, level, topic, title, prompt, code):
    return {"key": key, "language": language, "level": level, "topic": topic, "title": title, "prompt": prompt, "code": code.strip("\n") + "\n"}


WALKTHROUGHS = [
    walkthrough("py-swap", "python", "beginner", "Variables", "Swap two values",
                "Watch a and b trade places in one line: Python builds the pair (b, a) first, then unpacks it.", '''
a = 5
b = 9
print("before:", a, b)
a, b = b, a
print("after:", a, b)
'''),
    walkthrough("py-running-total", "python", "beginner", "Loops", "A running total",
                "Each turn of the loop takes the next price and adds it to total. Watch price and total change together.", '''
prices = [120, 45, 80]
total = 0
for price in prices:
    total = total + price
    print("added", price, "total is", total)
print("final:", total)
'''),
    walkthrough("py-fizzbuzz", "python", "beginner", "Conditions", "FizzBuzz",
                "For each number, the first matching condition wins, which is why 15 is checked before 3 and 5.", '''
for n in range(1, 16):
    if n % 15 == 0:
        print("FizzBuzz")
    elif n % 3 == 0:
        print("Fizz")
    elif n % 5 == 0:
        print("Buzz")
    else:
        print(n)
'''),
    walkthrough("py-factorial", "python", "intermediate", "Recursion", "Factorial with recursion",
                "Watch the call stack grow as factorial calls itself with smaller numbers, then shrink as each call returns.", '''
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print(factorial(4))
'''),
    walkthrough("py-bubble-sort", "python", "intermediate", "Sorting", "Bubble sort",
                "Neighbours that are out of order swap places, so the biggest value bubbles to the end on each pass.", '''
items = [5, 2, 4, 1]
for end in range(len(items) - 1, 0, -1):
    for i in range(end):
        if items[i] > items[i + 1]:
            items[i], items[i + 1] = items[i + 1], items[i]
print(items)
'''),
    walkthrough("py-binary-search", "python", "advanced", "Searching", "Binary search",
                "low and high close in on the target, halving the range each time: 6 items take at most 3 checks.", '''
items = [3, 8, 15, 23, 42, 57]
target = 42
low, high = 0, len(items) - 1
while low <= high:
    mid = (low + high) // 2
    print("checking", items[mid], "at", mid)
    if items[mid] == target:
        print("found at", mid)
        break
    if items[mid] < target:
        low = mid + 1
    else:
        high = mid - 1
'''),

    walkthrough("js-swap", "javascript", "beginner", "Variables", "Swap two values",
                "Destructuring builds [b, a] first, then assigns it back, so a and b trade places in one line.", '''
let a = 5;
let b = 9;
console.log("before:", a, b);
[a, b] = [b, a];
console.log("after:", a, b);
'''),
    walkthrough("js-running-total", "javascript", "beginner", "Loops", "A running total",
                "Each turn of the loop takes the next price and adds it to total. Watch price and total change together.", '''
const prices = [120, 45, 80];
let total = 0;
for (const price of prices) {
  total = total + price;
  console.log("added", price, "total is", total);
}
console.log("final:", total);
'''),
    walkthrough("js-fizzbuzz", "javascript", "beginner", "Conditions", "FizzBuzz",
                "For each number, the first matching condition wins, which is why 15 is checked before 3 and 5.", '''
for (let n = 1; n <= 15; n++) {
  if (n % 15 === 0) {
    console.log("FizzBuzz");
  } else if (n % 3 === 0) {
    console.log("Fizz");
  } else if (n % 5 === 0) {
    console.log("Buzz");
  } else {
    console.log(n);
  }
}
'''),
    walkthrough("js-factorial", "javascript", "intermediate", "Recursion", "Factorial with recursion",
                "Watch the call stack grow as factorial calls itself with smaller numbers, then shrink as each call returns.", '''
function factorial(n) {
  if (n <= 1) {
    return 1;
  }
  return n * factorial(n - 1);
}

console.log(factorial(4));
'''),
    walkthrough("js-bubble-sort", "javascript", "intermediate", "Sorting", "Bubble sort",
                "Neighbours that are out of order swap places, so the biggest value bubbles to the end on each pass.", '''
const items = [5, 2, 4, 1];
for (let end = items.length - 1; end > 0; end--) {
  for (let i = 0; i < end; i++) {
    if (items[i] > items[i + 1]) {
      [items[i], items[i + 1]] = [items[i + 1], items[i]];
    }
  }
}
console.log(items);
'''),
    walkthrough("js-binary-search", "javascript", "advanced", "Searching", "Binary search",
                "low and high close in on the target, halving the range each time: 6 items take at most 3 checks.", '''
const items = [3, 8, 15, 23, 42, 57];
const target = 42;
let low = 0;
let high = items.length - 1;
while (low <= high) {
  const mid = Math.floor((low + high) / 2);
  console.log("checking", items[mid], "at", mid);
  if (items[mid] === target) {
    console.log("found at", mid);
    break;
  }
  if (items[mid] < target) {
    low = mid + 1;
  } else {
    high = mid - 1;
  }
}
'''),
]

WALKTHROUGH_BY_KEY = {item["key"]: item for item in WALKTHROUGHS}
# The code lab's old challenges are problems now: where each one went.
OLD_CHALLENGES = {"sum-evens": "sum-of-even-numbers", "reverse-words": "reverse-words-in-a-string", "two-sum": "two-sum", "binary-search": "binary-search",
                  "flatten": "flatten-nested-list"}
