"""The code lab: challenges to solve with tests, and walkthroughs to watch run step by step. Code runs only in the
person's browser (Python with Pyodide, JavaScript in a sandboxed frame). The tests prove every Python solution passes
its tests and every starter fails one; the JavaScript ones are checked in a browser."""

RUNNABLE = {"python": "Python", "javascript": "JavaScript"}


def challenge(key, language, level, topic, title, prompt, starter, solution, tests):
    """tests: (call, expected) pairs. Python expects a literal (compared with ==); JavaScript expects JSON."""
    return {"key": key, "language": language, "level": level, "topic": topic, "title": title, "prompt": prompt,
            "starter": starter.strip("\n") + "\n", "solution": solution.strip("\n") + "\n", "tests": [{"call": call, "expected": expected} for call, expected in tests]}


def walkthrough(key, language, level, topic, title, prompt, code):
    return {"key": key, "language": language, "level": level, "topic": topic, "title": title, "prompt": prompt, "code": code.strip("\n") + "\n"}


CHALLENGES = [
    challenge("py-sum-evens", "python", "beginner", "Loops", "Add up the even numbers",
              "Write sum_evens(numbers) that returns the sum of the even numbers in the list. An empty list adds up to 0.",
              '''
def sum_evens(numbers):
    total = 0
    # Add each even number to total
    return total
''', '''
def sum_evens(numbers):
    total = 0
    for n in numbers:
        if n % 2 == 0:
            total += n
    return total
''', [("sum_evens([1, 2, 3, 4])", "6"), ("sum_evens([])", "0"), ("sum_evens([7, 9])", "0"), ("sum_evens([-2, 3, 10])", "8")]),
    challenge("py-reverse-words", "python", "beginner", "Strings", "Reverse the words",
              "Write reverse_words(sentence) that returns the words of the sentence in reverse order, separated by single spaces.",
              '''
def reverse_words(sentence):
    # Split, reverse, join
    return sentence
''', '''
def reverse_words(sentence):
    words = sentence.split()
    words.reverse()
    return " ".join(words)
''', [("reverse_words('hello world')", "'world hello'"), ("reverse_words('one')", "'one'"), ("reverse_words('a b c')", "'c b a'")]),
    challenge("py-char-counts", "python", "intermediate", "Dictionaries", "Count the letters",
              "Write char_counts(text) that returns a dictionary of how many times each letter appears. Skip spaces, and count capital and small letters together.",
              '''
def char_counts(text):
    counts = {}
    return counts
''', '''
def char_counts(text):
    counts = {}
    for ch in text.lower():
        if ch == " ":
            continue
        counts[ch] = counts.get(ch, 0) + 1
    return counts
''', [("char_counts('Aab')", "{'a': 2, 'b': 1}"), ("char_counts('')", "{}"), ("char_counts('a a')", "{'a': 2}")]),
    challenge("py-two-sum", "python", "intermediate", "Dictionaries", "Two numbers that add up",
              "Write two_sum(nums, target) that returns the positions [i, j], with i before j, of the two numbers that add up to target. There's always exactly one answer.",
              '''
def two_sum(nums, target):
    return []
''', '''
def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
    return []
''', [("two_sum([2, 7, 11, 15], 9)", "[0, 1]"), ("two_sum([3, 2, 4], 6)", "[1, 2]"), ("two_sum([1, 5, 1], 2)", "[0, 2]")]),
    challenge("py-binary-search", "python", "advanced", "Searching", "Binary search",
              "Write binary_search(items, target) for a sorted list: return the position of target, or -1 if it isn't there. Halve the range each step instead of checking every item.",
              '''
def binary_search(items, target):
    low, high = 0, len(items) - 1
    return -1
''', '''
def binary_search(items, target):
    low, high = 0, len(items) - 1
    while low <= high:
        mid = (low + high) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
''', [("binary_search([1, 3, 5, 7, 9], 7)", "3"), ("binary_search([1, 3, 5], 4)", "-1"), ("binary_search([], 1)", "-1"), ("binary_search([2], 2)", "0")]),
    challenge("py-flatten", "python", "advanced", "Recursion", "Flatten nested lists",
              "Write flatten(nested) that returns one flat list of all the values, however deeply the lists are nested.",
              '''
def flatten(nested):
    result = []
    return result
''', '''
def flatten(nested):
    result = []
    for item in nested:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result
''', [("flatten([1, [2, [3, 4]], 5])", "[1, 2, 3, 4, 5]"), ("flatten([])", "[]"), ("flatten([[[]]])", "[]"), ("flatten([[1], 2])", "[1, 2]")]),

    challenge("js-sum-evens", "javascript", "beginner", "Loops", "Add up the even numbers",
              "Write sumEvens(numbers) that returns the sum of the even numbers in the array. An empty array adds up to 0.",
              '''
function sumEvens(numbers) {
  let total = 0;
  // Add each even number to total
  return total;
}
''', '''
function sumEvens(numbers) {
  let total = 0;
  for (const n of numbers) {
    if (n % 2 === 0) {
      total += n;
    }
  }
  return total;
}
''', [("sumEvens([1, 2, 3, 4])", "6"), ("sumEvens([])", "0"), ("sumEvens([7, 9])", "0"), ("sumEvens([-2, 3, 10])", "8")]),
    challenge("js-reverse-words", "javascript", "beginner", "Strings", "Reverse the words",
              "Write reverseWords(sentence) that returns the words of the sentence in reverse order, separated by single spaces.",
              '''
function reverseWords(sentence) {
  // Split, reverse, join
  return sentence;
}
''', '''
function reverseWords(sentence) {
  const words = sentence.split(" ").filter(Boolean);
  return words.reverse().join(" ");
}
''', [('reverseWords("hello world")', '"world hello"'), ('reverseWords("one")', '"one"'), ('reverseWords("a b c")', '"c b a"')]),
    challenge("js-char-counts", "javascript", "intermediate", "Objects", "Count the letters",
              "Write charCounts(text) that returns an object of how many times each letter appears. Skip spaces, and count capital and small letters together.",
              '''
function charCounts(text) {
  const counts = {};
  return counts;
}
''', '''
function charCounts(text) {
  const counts = {};
  for (const ch of text.toLowerCase()) {
    if (ch === " ") continue;
    counts[ch] = (counts[ch] || 0) + 1;
  }
  return counts;
}
''', [('charCounts("Aab")', '{"a": 2, "b": 1}'), ('charCounts("")', "{}"), ('charCounts("a a")', '{"a": 2}')]),
    challenge("js-two-sum", "javascript", "intermediate", "Maps", "Two numbers that add up",
              "Write twoSum(nums, target) that returns the positions [i, j], with i before j, of the two numbers that add up to target. There's always exactly one answer.",
              '''
function twoSum(nums, target) {
  return [];
}
''', '''
function twoSum(nums, target) {
  const seen = new Map();
  for (let i = 0; i < nums.length; i++) {
    const need = target - nums[i];
    if (seen.has(need)) {
      return [seen.get(need), i];
    }
    seen.set(nums[i], i);
  }
  return [];
}
''', [("twoSum([2, 7, 11, 15], 9)", "[0, 1]"), ("twoSum([3, 2, 4], 6)", "[1, 2]"), ("twoSum([1, 5, 1], 2)", "[0, 2]")]),
    challenge("js-binary-search", "javascript", "advanced", "Searching", "Binary search",
              "Write binarySearch(items, target) for a sorted array: return the position of target, or -1 if it isn't there. Halve the range each step instead of checking every item.",
              '''
function binarySearch(items, target) {
  let low = 0;
  let high = items.length - 1;
  return -1;
}
''', '''
function binarySearch(items, target) {
  let low = 0;
  let high = items.length - 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    if (items[mid] === target) return mid;
    if (items[mid] < target) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return -1;
}
''', [("binarySearch([1, 3, 5, 7, 9], 7)", "3"), ("binarySearch([1, 3, 5], 4)", "-1"), ("binarySearch([], 1)", "-1"), ("binarySearch([2], 2)", "0")]),
    challenge("js-flatten", "javascript", "advanced", "Recursion", "Flatten nested arrays",
              "Write flatten(nested) that returns one flat array of all the values, however deeply the arrays are nested.",
              '''
function flatten(nested) {
  const result = [];
  return result;
}
''', '''
function flatten(nested) {
  const result = [];
  for (const item of nested) {
    if (Array.isArray(item)) {
      result.push(...flatten(item));
    } else {
      result.push(item);
    }
  }
  return result;
}
''', [("flatten([1, [2, [3, 4]], 5])", "[1, 2, 3, 4, 5]"), ("flatten([])", "[]"), ("flatten([[[]]])", "[]"), ("flatten([[1], 2])", "[1, 2]")]),
]

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

# Separate lookups: a challenge and a walkthrough can share a key (binary search is both).
CHALLENGE_BY_KEY = {item["key"]: item for item in CHALLENGES}
WALKTHROUGH_BY_KEY = {item["key"]: item for item in WALKTHROUGHS}
