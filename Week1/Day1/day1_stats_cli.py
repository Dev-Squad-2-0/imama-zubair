#Imama's Task 1 - Python Syntax, Control Flow, Functions
def mean(nums):
    return sum(nums) / len(nums)   #avg num


def median(nums):                   #middle num
    sorted_nums = sorted(nums)     #sorting for median
    n = len(sorted_nums)

    #even
    if n % 2 == 0:
        mid1 = sorted_nums[n // 2 - 1]
        mid2 = sorted_nums[n // 2]
        return (mid1 + mid2) / 2
    #odd
    else:
        return sorted_nums[n // 2]              #easier to do btw


def mode(nums):             #most frequent num
    frequency = {}              #dict to store num countss

    for num in nums:         
        if num in frequency:   #if more than 1 mode, we add it to the list
            frequency[num] += 1
        else:
            frequency[num] = 1          #normal case

    highest_count = max(frequency.values())     #finding the nums(s) with the most frequency

    modes = []                              #list of modes, if more than 1
    for num, count in frequency.items():        #finding those nums 
        if count == highest_count:
            modes.append(num)

    return modes



def mini(nums):
    smallest = nums[0]

    for num in nums:
        if num < smallest:
            smallest = num     #num becomes the smallest

    return smallest


def maxi(nums):
    largest = nums[0]

    for num in nums:
        if num > largest:
            largest = num  #num becomes the largest

    return largest

#main func
def main():
    print("\t\tTask 1 - Imama Zubair -> Python Syntax, Control Flow, Functions")

    try:
        user_input = input("\nEnter numbers separated by commas: ")

        nums = []                               #list of nums
        for val in user_input.split(","):
            nums.append(float(val))

        if len(nums) == 0:
            print("No nums entered")
            return

        print("\n\t\tResults")

        print(f"Mean:{mean(nums)}")
        print(f"Median:{median(nums)}")
        print(f"Mode:{mode(nums)}")
        print(f"Min:{mini(nums)}")
        print(f"Max:{maxi(nums)}")

    except ValueError:
        print("invalid input. Enter the right format")


main()