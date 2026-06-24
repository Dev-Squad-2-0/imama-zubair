# nums = []
# def max(nums):
#     large = nums[0]
#     for num in nums:
#         if num > large:
#             large = num
#     return large


# def min(nums):
#     small = nums[0]
#     for num in nums:
#         if num < small:
#             small = num
#     return small




# def main():
    # nums = [3, 1, 4, 1, 5, 9]
    # print("Max:", max(nums))
    # print("Min:", min(nums))

# main()


#FUNC that returns a sq or number


def sq_of_num(num):
    return num * num

def main():
    num = int(input("Enter a number: "))
    print("Square:", sq_of_num(num))

main()