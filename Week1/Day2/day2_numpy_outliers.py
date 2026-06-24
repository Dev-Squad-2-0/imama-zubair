import numpy as np

from numpy.lib.stride_tricks import sliding_window_view

#machine vibration sensor data, prolly measured in a.u. (arbitrary units)
data = np.array([
    3.9, 4.2, 4.5, 4.1,4.8,4.6,4.3, 4.7, 4.4, 4.9, 4.5, 4.6, 4.2,               #normal readings are b/w 4 and 5
      4.8, 4.7, 4.3, 15.4, 1.2, 4.5, 4.6, 4.7, 4.3, 4.2 ,4.4,
     4.6, 4.5, 4.7, 13.2, 5.1, 4.3,4.8, 4.6, 4.5, 12.2, -10.1])

print("Data:", data)
print("No. of data points: ", len(data))

win_size = 5

wins = sliding_window_view(data, win_size)          #windows that slide through 
print("Windows: ", wins)

#rolling statistics   
#rolling mean
rolling_mean = np.mean(wins, axis=1)
print("\nRolling Mean: ", np.round(rolling_mean, 2))

#rolling std
rolling_std = np.std(wins, axis=1)  #high std -> unstable, low std -> stable
print("Rolling Std: ", np.round(rolling_std, 2))

#rolling median
rolling_median = np.median(wins, axis=1)  #dont think we need this 
print("Rolling Median: ", np.round(rolling_median, 2))

#nrmalization (z-score)
mean = np.mean(data)
std = np.std(data)
print("Mean:", round(mean,2))
print("Std: ", round(std,2))
z_scores = (data - mean) / std                  #z-score formula (x - mean) / std
                                                #measures how many stds a data point is, above or below the mean
print("\n\nZ-scores: ", np.round(z_scores, 2))

#NEG Z-SCORES ARE BELOW AVERAGE, POS Z-SCORES ARE ABOVE AVERAGE and Z-SCORES CLOSE TO ZERO ARE NEAR THE MEAN


#for outliers 
#>2 std dev
outlier_flags = np.abs(z_scores) > 2
outliers = data[np.abs(z_scores) > 2]  #absolute value is used for both pos and neg outliers
print("\nOutlier Flags: ", outlier_flags)
print("\nOutliers: ", outliers)
print("\nNo. of outliers: ", len(outliers))


print("\n\n=====Since mean + std combo is not detecting all of the outlier, we are going to use the Median + IQR combo=====")

median = np.median(data)

Q1 = np.percentile(data, 25)            #first quart
Q3 = np.percentile(data, 75)            #3rd quart

IQR = Q3 - Q1                   

lower_fence = Q1 - 1.5 * IQR
upper_fence = Q3 + 1.5 * IQR

outlier_flags = (data < lower_fence) | (data > upper_fence)
outliers = data[outlier_flags]

print("\nMedian:", round(median, 2))
print("Q1:", round(Q1, 2))
print("Q3:", round(Q3, 2))
print("IQR:", round(IQR, 2))

print("\nLower Fence:", round(lower_fence, 2))
print("Upper Fence:", round(upper_fence, 2))

print("\nOutlier Flags:", outlier_flags)
print("\nOutliers:", outliers)
print("\nNo. of Outliers:", len(outliers))


print("\n\nNote: So since our data has certain values that are extreme but werent caught by mean + std combo,\nI ended up using the median + IQR combo since it catches outliers better")