from flask import Flask, request, jsonify
import cv2
import numpy as np
from io import BytesIO
import requests
import base64


app = Flask(__name__)
def ImageStitching(imageL,imageR, outname):

    # Convert images into gray scale
    grayL = cv2.cvtColor(imageL, cv2.COLOR_BGR2GRAY)
    grayR = cv2.cvtColor(imageR, cv2.COLOR_BGR2GRAY)
    
    
    ## OPTIMIZATION METHODS ##

    # create a mask image filled with zeros, the size of original image
    maskL = np.zeros(imageL.shape[:2], dtype=np.uint8)
    maskLT = np.zeros(imageL.shape[:2], dtype=np.uint8)
    maskR = np.zeros(imageR.shape[:2], dtype=np.uint8)
    maskRT = np.zeros(imageR.shape[:2], dtype=np.uint8)
    
    imageL_w = imageL.shape[1]
    imageL_h = imageL.shape[0]
    imageR_w = imageR.shape[1]
    imageR_h = imageR.shape[0]
    
    '''
    # Rectangle Masking with Percentage
    
    # As we know which image is left and which image is right, we can only scan the right and left 
    # part of images by scaning %75 part of an image, program can work in a more optimized manner.

    
    # My test results showed that scanning only %75 of the images helps us save 2-3 seconds and this value
    # still can increase as we reduce the scan area without losing any details in panorama
    
    #Input desired percentage to be scanned
    percentage = 75
    alt_percentage = 100-percentage
    
    
    # draw desired ROI on the mask image
    # (mask, first position, second position, color, thickness)
    cv2.rectangle(maskL, (int(imageL_w*alt_percentage/100),0), (int(imageL_w),int(imageL_h)), (255), thickness = -1)
    cv2.rectangle(maskR, (0,0), (int(percentage*imageR_w/100),int(imageR_h)), (255), thickness = -1)
    '''
    
    
    # Bucketing
    
    # We can seperate our image into little rectangles and can only take some of those rectangles to save computing time. 
    # As these rectangles are homogenously disturbed through our image, precision of the stitching doesn't change.
    
    
    # My test results showed that using 50x50 mask of the images helps us save 4-5 seconds (which is very drastic) for 
    # each stitching and this value still can increase as we reduce the scan area without losing any details in panoram
    
    flagl= 0
    flagr = 0
    
    # I have decided to combine both methods of bucketing and masking with percentage to optimize the program
    # even more. I have seen a 5-6 seconds time save with both optimization tecniques implemented at the same time.
    
    #Input desired percentage to be scanned
    percentage = 80
    alt_percentage = 100-percentage
    
    for col in range(0, imageL_h, 50): # 0, 50, 100, ...
        for row in range(int(imageL_w*alt_percentage/100), imageL_w, 100):
            if flagl%2 == 0:
                cv2.rectangle(maskLT, (row,col), (row+50,col+50), (255), thickness = -1)
                maskL += maskLT
            else:
                cv2.rectangle(maskLT, (row+50,col), (row+100,col+50), (255), thickness = -1)
                maskL += maskLT
        flagl += 1
        
        
    for col in range(0, imageR_h, 50): # 0, 50, 100, ...
        for row in range(0, int(imageR_w*percentage/100), 100): 
            if flagr%2 == 0:
                cv2.rectangle(maskRT, (row,col), (row+50,col+50), (255), thickness = -1)
                maskR += maskRT
            else:
                cv2.rectangle(maskRT, (row+50,col), (row+100,col+50), (255), thickness = -1)
                maskR += maskRT
        flagr += 1
       
    
    #cv2.imshow('maskR', maskR)
    #cv2.imshow('maskL', maskL)


    
    

    sift = cv2.SIFT_create() 

    left_keypoints, left_descriptor = sift.detectAndCompute(grayL, maskL)   # Change maskL to none if no mask
    right_keypoints, right_descriptor = sift.detectAndCompute(grayR, maskR) # Change maskR to None if no mask
    

    # print("Number of Keypoints Detected In The Left Image: ", len(left_keypoints))
    
    # print("Number of Keypoints Detected In The Right Image: ", len(right_keypoints))
    
    
    bf = cv2.BFMatcher(cv2.NORM_L1, crossCheck = False) 
                                                        
    matches = bf.match(left_descriptor, right_descriptor)

    matches = sorted(matches, key = lambda x : x.distance)

  
    result = cv2.drawMatches(imageL, left_keypoints, imageR, right_keypoints, matches[:100], grayR, flags = 2)
    
    # cv2.imshow('SIFT Matches', result)
    
    # #print("--- %s seconds ---" % (time.time() - start_time)) # Used for testing 
    # # Print total number of matching points between the training and query images
    # print("\nSIFT Matches are ready. \nNumber of Matching Keypoints: ", len(matches))
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    
    # KNN Matching
    
    ratio = 0.85 
    raw_matches = bf.knnMatch(left_descriptor, right_descriptor, k=2)   
    good_points = []                                                   
    good_matches=[] 
    
    for match1, match2 in raw_matches: # We check every two matches for each point
        if match1.distance < match2.distance * ratio:               # If points inlies in our desired treshold 
            good_points.append((match1.trainIdx, match1.queryIdx))  # we declare them as good points.
            good_matches.append([match1])
    
    
    # We will only display first 100 matches for simplicity
    knnResult = cv2.drawMatchesKnn(imageL, left_keypoints, imageR, right_keypoints, good_matches[:100], None, flags=2)
    # cv2.imshow('KNN Matches', knnResult)
    
    # print("\nKNN Matches are ready. \nNumber of Matching Keypoints: ", len(good_matches))
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    
    # Calculating Homography using good matches and RANSAC
    
    # I have selected ratio, min_match and RANSAC values according to a study by Caparas, Fajardo and Medina
    # said paper: https://www.warse.org/IJATCSE/static/pdf/file/ijatcse18911sl2020.pdf
    
    min_match = 10
    
    if len(good_points) > min_match: # Check if we have enough good points (minimum of 4 needed to calculate H)
        imageL_kp = np.float32(
            [left_keypoints[i].pt for (_, i) in good_points])
        imageR_kp = np.float32(
            [right_keypoints[i].pt for (i, _) in good_points])
        H, status = cv2.findHomography(imageR_kp, imageL_kp, cv2.RANSAC,5.0)    # H gives us a 3x3 Matrix for our
                                                                                # desired transformation.
    
    # Assigning Panaroma Height and Width
    
    height_imgL = imageL.shape[0] # Shape command gives us height and width of an image in a list 
    width_imgL = imageL.shape[1]  # 0 -> height, 1 -> width
    width_imgR = imageR.shape[1]
    height_panorama = height_imgL
    width_panorama = width_imgL + width_imgR
    
  
    
    def create_mask(img1,img2,version):
        smoothing_window_size=800
        height_img1 = img1.shape[0] # Shape command gives us height and width of an image in a list 
        width_img1 = img1.shape[1]  # 0 -> height, 1 -> width
        width_img2 = img2.shape[1]
        height_panorama = height_img1
        width_panorama = width_img1 + width_img2
        offset = int(smoothing_window_size / 2)
        barrier = img1.shape[1] - int(smoothing_window_size / 2)
        mask = np.zeros((height_panorama, width_panorama))
        if version== 'left_image':  # Used for creating mask1
            mask[:, barrier - offset:barrier + offset ] = np.tile(np.linspace(1, 0, 2 * offset ).T, (height_panorama, 1))
            mask[:, :barrier - offset] = 1
        else:                       # Used for creating mask2 
            mask[:, barrier - offset :barrier + offset ] = np.tile(np.linspace(0, 1, 2 * offset ).T, (height_panorama, 1))
            mask[:, barrier + offset:] = 1
        return cv2.merge([mask, mask, mask])
    
    # Creating the panorama
    
    height_img1 = imageL.shape[0]
    width_img1 = imageL.shape[1]
    width_img2 = imageR.shape[1]
    height_panorama = height_img1
    width_panorama = width_img1 + width_img2
    
    panorama1 = np.zeros((height_panorama, width_panorama, 3))  # 1. create the shape of our panorama
    mask1 = create_mask(imageL,imageR,version='left_image')     # 2. create our mask with this shape
    panorama1[0:imageL.shape[0], 0:imageL.shape[1], :] = imageL # 3. include color of each pixel to the shape
    panorama1 *= mask1                                          # 4. apply our mask to panorama
    mask2 = create_mask(imageL,imageR,version='right_image')
    
    #For right half of the panorama, we warp it with H we found and apply the mask
    panorama2 = cv2.warpPerspective(imageR, H, (width_panorama, height_panorama))*mask2
    result=panorama1+panorama2 #We combine both of them to have our result


    #Normalize panoramas for display with imshow command
    norm_p1 = cv2.normalize(panorama1, None, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_32F)
    norm_p2 = cv2.normalize(panorama2, None, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_32F)

    # Displaying all results
    
    # cv2.imshow('Panorama_1', norm_p1)
    
    # print("\nPanorama 1 is ready")
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    
    '''
    cv2.imshow('Mask_1', mask1)

    print("\nMask_1 is ready")
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    '''
    
    # cv2.imshow('Panorama_2', norm_p2)

    # print("\nPanorama 2 is ready")
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    
    '''
    cv2.imshow('Mask_2', mask2)

    print("\nMask_2 is ready")
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    '''
    
    # Get rid of black borders created by perspective differences and unused space
    
    rows, cols = np.where(result[:, :, 0] != 0) # Check if a pixel is pure black or not (0-255) and get the ones 
    min_row, max_row = min(rows), max(rows) + 1 # that are not black as rows and cols
    min_col, max_col = min(cols), max(cols) + 1
    final_result = result[min_row:max_row, min_col:max_col, :] # Resize image without black borders

    norm_pf = cv2.normalize(final_result, None, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_32F)

    cv2.imwrite(outname+'.jpg', final_result)

    stitched_image = cv2.imread(outname + '.jpg')
    return stitched_image
    
    
    
    # cv2.imshow(outname, norm_pf)
    
    # print("\nFinal Panorama is created with the name "+outname+".jpg")
    # cv2.waitKey(0)
    
    # A simple code to fix a bug preventing the last image window to close
    # cv2.waitKey(1)
    # cv2.destroyAllWindows()
    for i in range (1,5):
        cv2.waitKey(1)
        return


def download_image(url):
        response = requests.get(url)
        return cv2.imdecode(np.frombuffer(response.content, np.uint8), -1)


@app.route('/stitch', methods=['POST'])
def stitch_images():
    data = request.json
    print(data)
    # ImageStitching(image1, image2, output_name)
    image_urls = data['image_urls']
    image1 = download_image(image_urls[0])
    image2 = download_image(image_urls[1])
   
    outname = "op"

    # Download images from URLs and convert to OpenCV format
    # images = []
    # for url in image_urls:
    #     # Download image using your preferred method (e.g., requests library)
    #     # Example: response = requests.get(url)
    #     Example: image = cv2.imdecode(np.fromstring(response.content, np.uint8), cv2.IMREAD_COLOR)
    #     # Add the downloaded image to the images list
    #     images.append(image)

    # Call ImageStitching function
    responseData=ImageStitching(image1, image2, outname)
    retval, buffer = cv2.imencode('.jpg', responseData)
    stitched_image_base64 = base64.b64encode(buffer).decode('utf-8')

    # cloudinary.uploader.upload(responseData, 
    # public_id = "checking")
    result = {'message': stitched_image_base64}
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=False,host='0.0.0.0')
