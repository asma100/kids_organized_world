def is_checked(image, x, y, size=20):
    roi = image[y:y+size, x:x+size]
    return roi.mean() < 200  # dark = checked



    results = {}

for task, (x, y) in tasks.items():
    results[task] = is_checked(image, x, y)