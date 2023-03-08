'''
This module was adapted from a module in https://github.com/HuTobias/HIGHLIGHTS-LRP
Date: 2020
commit: 834bf795ee37a74b611beb79851438e9a8afd676
License: MIT


This module implements sanity checks for saliency maps.
To this end the layers in the model are cascadingly randomized and for each step we create a copy of the model.
Then we create gameplay and saliency map streams for each of those models, using the decisions of the original model,
 such that all models get the same input states.
Finally we compare the generated saliency maps of all models.
'''

import numpy as np
import os
import matplotlib.pyplot as plt
from scipy.stats import pearsonr, spearmanr
from skimage.metrics import structural_similarity as ssim
from skimage.feature import hog
import pandas as pd
import keras
import seaborn as sns
import gym
import skimage.segmentation as seg

from applications.atari.custom_atari_wrapper import atari_wrapper
from applications.atari.explanation import explainer
import applications.atari.used_parameters as used_params

import tensorflow as tf
import keras.backend as K

import timeit

def show_and_save_plt(ax ,file_name, y_label=None, ylim =None, label_size = 18, tick_size = 14):
    """
    Shows and saves the given plot and defines the appearance of the final plot.
    :param ax: the plot to be saved.
    :param file_name: save file name where the file is saved.
    :param y_label: the y axis label displayed
    :param title: titel of displayed in the plot (currently not used)
    :param ylim: limits of the y axis.
    :param label_size: font size of the label text
    :param tick_size: font size of the tick numbers
    """
    #this only works the second time the function is used, since it sets the style for future plots.
    # It was still more convenient this way. #TODO fix this
    sns.set_style("whitegrid")

    if y_label != None:
        plt.ylabel(y_label)
    plt.xlabel(None)
    if ylim != None:
        ax.set(ylim=ylim)

    try:
        ax.yaxis.label.set_size(label_size)
        ax.xaxis.label.set_size(label_size)
    except:
        try:
            plt.ylabel(y_label, fontsize=label_size)
            plt.xlabel(fontsize=label_size)
        except Exception as e:
            print(e)

    plt.xticks(fontsize=tick_size)
    plt.yticks(fontsize=tick_size)

    file_name = os.path.join('figures/sanity_checks', file_name)
    if not (os.path.isdir(file_name)):
        os.makedirs(file_name)
        os.rmdir(file_name)
    plt.tight_layout()
    plt.savefig(file_name)

    plt.show()


def normalise_image(image):
    '''normalises image by forcing the min and max values to 0 and 1 respectively
     :param image: the input image
    :return: normalised image as numpy array
    '''
    try:
        image = np.asarray(image)
    except:
        print('Cannot convert image to array')
    image = image - image.min()
    if image.max() != 0:
        image = image / image.max()
    return image


def rand_layer(layer, mean = 0, SD = 0.1):
    '''Custom layer randomization for testing purposes.'''
    weights_shape = layer.get_weights()[0].shape
    bias_shape = layer.get_weights()[1].shape
    rand_weights =  np.random.normal(mean,SD,weights_shape)
    rand_bias = np.random.normal(mean,SD,bias_shape)
    layer.set_weights([rand_weights, rand_bias])


def init_layer(layer):
    ''' Re-initializes the given layer with the original initializer to achieve randomization of the layer that is
    within reasonable bounds for that layer.
    :param layer: the layer to be randomized
    :return: nothing, the given layer is randomized
    '''
    session = K.get_session()
    weights_initializer = tf.variables_initializer(layer.weights)
    session.run(weights_initializer)


def copy_model(model):
    '''
    Copies a keras model including the weights
    :param model: the model to be copied
    :return: the new copy of the model
    '''
    model_m1 = keras.models.clone_model(model)
    model_m1.set_weights(model.get_weights())
    return model_m1


def check_models(model1, model):
    ''' checks if two models have the same weights, to make sure that a layer was randomized.'''
    for i in range(1,7):
        if i != 4:
            print('layer ', i)
            print( (model1.get_layer(index=i).get_weights()[0] == model.get_layer(index=i).get_weights()[0]).all() )
            print( (model1.get_layer(index=i).get_weights()[1] == model.get_layer(index=i).get_weights()[1]).all() )


def calc_sim(learned_relevance, random_relevance, _pearson_list, _ssim_list, _spearman_list):
    ''' Helper function to calculate the similarities of two saliency maps (for learned weights and partly random wheights).
    Only works in this code, since the similarity lists are created elsewhere. '''
    #normalizing:
    learned_relevance = normalise_image(learned_relevance)
    random_relevance = normalise_image(random_relevance)
    neg_random_relevance = 1 - random_relevance

    spearman, spearman2 = spearmanr(random_relevance.flatten(), learned_relevance.flatten(), nan_policy='omit')
    test, _ = spearmanr(neg_random_relevance.flatten(), learned_relevance.flatten(), nan_policy='omit')
    spearman = max(spearman, test)

    # ssim_val = ssim(random_relevance,learned_relevance, multichannel=True)
    ssim_val = ssim(random_relevance.flatten(), learned_relevance.flatten(), data_range=1)
    test = ssim(neg_random_relevance.flatten(), learned_relevance.flatten(), data_range=1)
    ssim_val = max(ssim_val, test)

    kwargs = {"pixels_per_cell":(3,3)}
    random_hog = hog(random_relevance, **kwargs)
    learned_hog = hog(learned_relevance, **kwargs)
    pearson, _ = pearsonr(random_hog, learned_hog)

    neg_random_hog = hog(neg_random_relevance, **kwargs)
    test, _ = pearsonr(neg_random_hog, learned_hog)
    pearson = max(pearson, test)


    _pearson_list.append(pearson)
    _ssim_list.append(ssim_val)
    _spearman_list.append(spearman)


def sanity_check( game, approach, _file_name, **kwargs):
    """
    calculate the sanity check for 1000 steps of the agent
    :param game: the game environment for the sanity check
    :param approach: the saliency map approach that should be evaluated
    :param _file_name:  the file name for the results
    :param kwargs: the keyword arguments for the saliency map approach
    :return: nothing, the results are saved
    """
    steps = 1001

    dir_name = os.path.join("results", game)
    if not os.path.isdir(dir_name):
        os.makedirs(dir_name)
    _file_name = os.path.join(dir_name, _file_name)

    # create empty list to be filled later
    pearson_list = []
    ssim_list = []
    spearman_list = []
    model_list = []
    action_list = []

    # generate stream of states, actions, and saliency maps
    np.random.seed(42)

    if game == "pacman":
        model = keras.models.load_model('../models/MsPacman_5M_ingame_reward.h5')
        env = gym.make('MsPacmanNoFrameskip-v4')
    elif game == "breakout":
        model = keras.models.load_model('../models/BreakoutIngame_5M.h5')
        env = gym.make("BreakoutNoFrameskip-v4")
    elif game == "spaceInvaders":
        model = keras.models.load_model('../models/SpaceInvadersIngame_5M.h5')
        env = gym.make("SpaceInvadersNoFrameskip-v4")
    elif game == "frostbite":
        model = keras.models.load_model('../models/FrostbiteIngame_5M.h5')
        env = gym.make("FrostbiteNoFrameskip-v4")

    model.summary()

    env.reset()
    wrapper = atari_wrapper(env)
    if (game == "spaceInvaders") | (game == "breakout"):
        wrapper.fire_reset = True
    wrapper.reset(noop_max=1)


    # create analyzer for fully trained model
    original_analyzer = explainer(model)

    # create analyzer for model with randomized last layer
    model1 = copy_model(model)
    layer = model1.get_layer(index=6)
    init_layer(layer)
    check_models(model1, model)
    analyzer1 = explainer(model1)

    # create analyzer for model where the two last layers are randomized
    model2 = copy_model(model1)
    layer = model2.get_layer(index=5)
    init_layer(layer)
    check_models(model2, model1)
    analyzer2 = explainer(model2)

    # create analyzer for model where the three last layers are randomized
    model3 = copy_model(model2)
    layer = model3.get_layer(index=3)
    init_layer(layer)
    check_models(model3, model2)
    analyzer3 = explainer(model3)

    # create analyzer for model where the four last layers are randomized
    model4 = copy_model(model3)
    layer = model4.get_layer(index=2)
    init_layer(layer)
    check_models(model4, model3)
    analyzer4 = explainer(model4)

    # create analyzer for model where all layers are randomized
    model5 = copy_model(model4)
    layer = model5.get_layer(index=1)
    init_layer(layer)
    check_models(model5, model4)
    analyzer5 = explainer(model5)

    if approach == "noise":
        og_saliency_fn = (
            lambda x, **kwargs2: original_analyzer.generate_greydanus_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_1 = (lambda x, **kwargs2: analyzer1.generate_greydanus_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_2 = (
            lambda x, **kwargs2: analyzer2.generate_greydanus_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_3 = (
            lambda x, **kwargs2: analyzer3.generate_greydanus_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_4 = (
            lambda x, **kwargs2: analyzer4.generate_greydanus_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_5 = (
            lambda x, **kwargs2: analyzer5.generate_greydanus_explanation(input=x, **kwargs, **kwargs2))

    if approach == "occl":
        og_saliency_fn = (
            lambda x, **kwargs2: original_analyzer.generate_occlusion_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_1 = (lambda x, **kwargs2: analyzer1.generate_occlusion_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_2 = (
            lambda x, **kwargs2: analyzer2.generate_occlusion_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_3 = (
            lambda x, **kwargs2: analyzer3.generate_occlusion_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_4 = (
            lambda x, **kwargs2: analyzer4.generate_occlusion_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_5 = (
            lambda x, **kwargs2: analyzer5.generate_occlusion_explanation(input=x, **kwargs, **kwargs2))

    if approach == "rise":
        og_saliency_fn = (
            lambda x, **kwargs2: original_analyzer.generate_rise_prediction(input=x, **kwargs, **kwargs2))
        saliency_fn_1 = (
            lambda x, **kwargs2: analyzer1.generate_rise_prediction(input=x, **kwargs, **kwargs2))
        saliency_fn_2 = (
            lambda x, **kwargs2: analyzer2.generate_rise_prediction(input=x, **kwargs, **kwargs2))
        saliency_fn_3 = (
            lambda x, **kwargs2: analyzer3.generate_rise_prediction(input=x, **kwargs, **kwargs2))
        saliency_fn_4 = (
            lambda x, **kwargs2: analyzer4.generate_rise_prediction(input=x, **kwargs, **kwargs2))
        saliency_fn_5 = (
            lambda x, **kwargs2: analyzer5.generate_rise_prediction(input=x, **kwargs, **kwargs2))

    if approach == "lime":
        og_saliency_fn = (
            lambda x, **kwargs2: original_analyzer.generate_lime_explanation(input=x, **kwargs, **kwargs2)[2])
        saliency_fn_1 = (
            lambda x, **kwargs2: analyzer1.generate_lime_explanation(input=x, **kwargs, **kwargs2)[2])
        saliency_fn_2 = (
            lambda x, **kwargs2: analyzer2.generate_lime_explanation(input=x, **kwargs, **kwargs2)[2])
        saliency_fn_3 = (
            lambda x, **kwargs2: analyzer3.generate_lime_explanation(input=x, **kwargs, **kwargs2)[2])
        saliency_fn_4 = (
            lambda x, **kwargs2: analyzer4.generate_lime_explanation(input=x, **kwargs, **kwargs2)[2])
        saliency_fn_5 = (
            lambda x, **kwargs2: analyzer5.generate_lime_explanation(input=x, **kwargs, **kwargs2)[2])

    if approach == "sarfa":
        og_saliency_fn = (
            lambda x, **kwargs2: original_analyzer.generate_sarfa_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_1 = (lambda x, **kwargs2: analyzer1.generate_sarfa_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_2 = (
            lambda x, **kwargs2: analyzer2.generate_sarfa_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_3 = (
            lambda x, **kwargs2: analyzer3.generate_sarfa_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_4 = (
            lambda x, **kwargs2: analyzer4.generate_sarfa_explanation(input=x, **kwargs, **kwargs2))
        saliency_fn_5 = (
            lambda x, **kwargs2: analyzer5.generate_sarfa_explanation(input=x, **kwargs, **kwargs2))


    fixed_start = True
    if fixed_start:
        if game == "pacman":
            wrapper.fixed_reset(200, 0)  # the MsPacman game does react to the first actions
        else:
            wrapper.fixed_reset(1, 0)
    for _ in range(steps):
        if _ % 10 == 0:
            print(_)
            print(timeit.default_timer())
        if _ < 4:
            action = env.action_space.sample()
            # to have more controll over the fixed starts
            if fixed_start:
                if game == "breakout":
                    action = 1 # this makes breakout start much faster
                else:
                    action = 0
            # In order for RISE to use the same Masks for all networks, we generate them once here
            if approach == "rise":
                if _ == 3:
                    og_saliency_map = og_saliency_fn(stacked_frames)
                    analyzer1.rise_masks = original_analyzer.rise_masks
                    analyzer1.masks_generated = True
                    analyzer2.rise_masks = original_analyzer.rise_masks
                    analyzer2.masks_generated = True
                    analyzer3.rise_masks = original_analyzer.rise_masks
                    analyzer3.masks_generated = True
                    analyzer4.rise_masks = original_analyzer.rise_masks
                    analyzer4.masks_generated = True
                    analyzer5.rise_masks = original_analyzer.rise_masks
                    analyzer5.masks_generated = True
        else:
            my_input = np.expand_dims(stacked_frames, axis=0)
            output = model.predict(
                my_input)  # this output corresponds with the output in baseline if --dueling=False is correctly set for baselines.
            my_input = np.squeeze(my_input)  # the saliency methods expect the input without batch dimension

            action = np.argmax(np.squeeze(output))

            # analyze fully trained model
            og_saliency_map = og_saliency_fn(my_input, neuron_selection=action)
            og_saliency_map = np.squeeze(og_saliency_map)
            # save the state
            # ave_raw_data(my_input,save_file_state, _)

            # create saliency map for model where the last layer is randomized
            saliency_map_1 = np.squeeze(saliency_fn_1(my_input, neuron_selection=action))
            # calculate similarities and append to lists.
            calc_sim(og_saliency_map, saliency_map_1, pearson_list, ssim_list, spearman_list)
            # save chosen action and the layer that was randomized in in this instance
            action_list.append(action)
            model_list.append(1)

            # see above but last two layers are randomized.
            saliency_map_2 = np.squeeze(saliency_fn_2(my_input, neuron_selection=action))
            calc_sim(og_saliency_map, saliency_map_2, pearson_list, ssim_list, spearman_list)
            action_list.append(action)
            model_list.append(2)

            # see above but last three layers are randomized.
            saliency_map_3 = np.squeeze(saliency_fn_3(my_input, neuron_selection=action))
            calc_sim(og_saliency_map, saliency_map_3, pearson_list, ssim_list, spearman_list)
            action_list.append(action)
            model_list.append(3)

            # see above but last four layers are randomized.
            saliency_map_4 = np.squeeze(saliency_fn_4(my_input, neuron_selection=action))
            calc_sim(og_saliency_map, saliency_map_4, pearson_list, ssim_list, spearman_list)
            action_list.append(action)
            model_list.append(4)

            # see above but all layers are randomized.
            saliency_map_5 = np.squeeze(saliency_fn_5(my_input, neuron_selection=action))
            calc_sim(og_saliency_map, saliency_map_5, pearson_list, ssim_list, spearman_list)
            action_list.append(action)
            model_list.append(5)

            ## random tests uniform
            test = np.random.rand(84, 84)
            calc_sim(og_saliency_map, test, pearson_list, ssim_list, spearman_list)
            action_list.append(action)
            model_list.append(6)

            ## random tests gaussian
            test = np.random.normal(size=(84, 84))
            calc_sim(og_saliency_map, test, pearson_list, ssim_list, spearman_list)
            action_list.append(action)
            model_list.append(7)

        stacked_frames, observations, reward, done, info = wrapper.step(action)
        # env.render()

    data_frame = pd.DataFrame(columns=['rand_layer', 'pearson', 'ssim', 'spearman', 'action'])
    data_frame['rand_layer'] = model_list
    data_frame['pearson'] = pearson_list
    data_frame['ssim'] = ssim_list
    data_frame['spearman'] = spearman_list
    data_frame['action'] = action_list

    data_frame.to_csv(_file_name)
    env.close()


if __name__ == '__main__':

    games = ["pacman", "breakout", "spaceInvaders", "frostbite"]

    # NOISE SENSITIVITY
    APPROACH = "noise"
    RADIUS = used_params.NOISE_RADIUS
    for GAME in games:
        BLUR = False
        RAW_DIFF = False
        file_name = used_params.NOISE_NAME + "_" + str(BLUR) + '_' + str(RAW_DIFF) + ".csv"
        sanity_check(game=GAME, approach=APPROACH, _file_name=file_name, r=RADIUS, blur=BLUR, raw_diff=RAW_DIFF)

        BLUR = True
        RAW_DIFF = True
        file_name = used_params.NOISE_NAME + "_" + str(BLUR) + '_' + str(RAW_DIFF) + ".csv"
        sanity_check(game=GAME, approach=APPROACH, _file_name=file_name, r=RADIUS, blur=BLUR, raw_diff=RAW_DIFF)

        BLUR = True
        RAW_DIFF = False
        file_name = used_params.NOISE_NAME + "_" + str(BLUR) + '_' + str(RAW_DIFF) + ".csv"
        sanity_check(game=GAME, approach=APPROACH, _file_name=file_name, r=RADIUS, blur=BLUR, raw_diff=RAW_DIFF)


    ### OCCLUSION SENSITIVITY
    APPROACH = "occl"
    PATCH_SIZE = used_params.OCCL_PATCH_SIZE
    COLOR = used_params.OCCL_COLOR
    SOFTMAX = used_params.OCCL_SOFTMAX
    for GAME in games:
        file_name = used_params.OCCL_NAME + ".csv"
        sanity_check(game=GAME, approach=APPROACH, _file_name=file_name, patch_size=PATCH_SIZE, color=COLOR
                     , use_softmax=SOFTMAX)

    ### RISE
    APPROACH = "rise"
    PROBABILITY = used_params.RISE_PROBABILITY
    MASK_SIZE = used_params.RISE_MASK_SIZE
    NUM_MASKS = used_params.RISE_NUM_MASKS
    SOFTMAX = used_params.RISE_SOFTMAX
    for GAME in games:
        file_name = used_params.RISE_NAME + ".csv"
        sanity_check(game=GAME, approach=APPROACH, _file_name=file_name, probability = PROBABILITY,
                     mask_size = MASK_SIZE, number_of_mask=NUM_MASKS, use_softmax=SOFTMAX)

    ### SARFA:
    APPROACH = "sarfa"
    for GAME in games:
        file_name = used_params.SARFA_NAME + ".csv"
        sanity_check(game=GAME, approach=APPROACH, _file_name=file_name,
                     r=used_params.SARFA_RADIUS, blur=used_params.SARFA_BLUR)

    ### LIME
    APPROACH = "lime"
    for GAME in games:
        file_name = used_params.SLIC_NAME + ".csv"
        segmentation_fn = (lambda x: seg.slic(x, n_segments=used_params.SLIC_N_SEGMENTS,
                                              compactness=used_params.SLIC_COMPACTNESS, sigma=used_params.SLIC_SIGMA))
        sanity_check(game=GAME, approach=APPROACH, _file_name=file_name, hide_img=False, positive_only=True,
                     segmentation_fn=segmentation_fn, num_samples=used_params.SLIC_NUM_SAMPLES)

        file_name = used_params.QUICKSHIFT_NAME + ".csv"
        segmentation_fn = (lambda x: seg.quickshift(x, kernel_size=used_params.QUICKSHIFT_KERNEL_SIZE,
                                                    max_dist=used_params.QUICKSHIFT_MAX_DIST,
                                                    ratio=used_params.QUICKSHIFT_RATIO, convert2lab=False))
        sanity_check(game=GAME, approach=APPROACH, _file_name=file_name, hide_img=False, positive_only=True,
                     segmentation_fn=segmentation_fn,  num_samples = used_params.QUICKSHIFT_NUM_SAMPLES)

        file_name = used_params.FELZ_NAME + ".csv"
        segmentation_fn = (
            lambda x: seg.felzenszwalb(x, scale=used_params.FELZ_SCALE, sigma=used_params.FELZ_SIGMA,
                                       min_size=used_params.FELZ_MIN_SIZE))
        sanity_check(game=GAME, approach=APPROACH, _file_name=file_name, hide_img=False, positive_only=True,
                     segmentation_fn=segmentation_fn, num_samples=used_params.FELZ_NUM_SAMPLES)
