import json
x={
    'type': 'KittiDataset',
     'root_path': '/content/drive/MyDrive/Graduation_Project/ObjectDetection3D/data_object_velodyne/'
     , 'info_path': '/content/drive/MyDrive/Graduation_Project/ObjectDetection3D/data_object_velodyne/kitti_infos_train.pkl', 
     'class_names': ['Car'], 
     'pipeline': [{'type': 'LoadPointCloudFromFile'}, 
     {'type': 'LoadPointCloudAnnotations', 'with_bbox': True, 'enable_difficulty_level': False},
    {'type': 'Preprocess', 'cfg': {'mode': 'train', 'shuffle_points': True, 'gt_loc_noise': [1.0, 1.0, 0.5], 'gt_rot_noise': [-0.785, 0.785], 'global_rot_noise': [-0.785, 0.785], 'global_scale_noise': [0.95, 1.05], 'global_rot_per_obj_range': [0, 0], 'global_trans_noise': [0.0, 0.0, 0.0], 'remove_points_after_sample': True, 'gt_drop_percentage': 0.0, 'gt_drop_max_keep_points': 15, 'remove_environment': False, 'remove_unknown_examples': False, 'db_sampler': {'type': 'GT-AUG', 'enable': True, 'db_info_path': '/content/drive/MyDrive/Graduation_Project/ObjectDetection3D/data_object_velodyne/dbinfos_train.pkl', 'sample_groups': [{'Car': 15}], 'db_prep_steps': [{'filter_by_min_num_points': {'Car': 5}}, {'filter_by_difficulty': [-1]}],
     'global_random_rotation_range_per_object': [0, 0], 'rate': 1.0, 'gt_random_drop': -1, 'gt_aug_with_context': -1, 'gt_aug_similar_type': False}, 'class_names': ['Car'], 'symmetry_intensity': False, 'enable_similar_type': True, 'min_points_in_gt': -1, 'data_aug_with_context': -1, 'data_aug_random_drop': -1}}, 
     {'type': 'Voxelization', 'cfg': 
     {'range': [0, -40.0, -3.0, 70.4, 40.0, 1.0], 'voxel_size': [0.05, 0.05, 0.1], 'max_points_in_voxel': 5, 'max_voxel_num': 20000, 'far_points_first': False}},
      {'type': 'AssignTarget', 'cfg': 
      {'box_coder': {'type': 'ground_box3d_coder', 'n_dim': 7, 'linear_dim': False, 'encode_angle_vector': False},
       'target_assigner': {'type': 'iou', 
       'anchor_generators': [{'type': 'anchor_generator_range', 'sizes': [1.6, 3.9, 1.56], 
       'anchor_ranges': [0, -40.0, -1.0, 70.4, 40.0, -1.0], 
       'rotations': [0, 1.57], 
       'matched_threshold': 0.6, 'unmatched_threshold': 0.45, 'class_name': 'Car'}],
        'sample_positive_fraction': -1, 'sample_size': 512, 
        'region_similarity_calculator': {'type': 'nearest_iou_similarity'},
         'pos_area_threshold': -1, 'tasks': [{'num_class': 1, 'class_names': ['Car']}]},
          'out_size_factor': 8, 'debug': False, 'enable_similar_type': True}}, {'type': 'Reformat'}]}

fil= open('x.json','w')
json.dump(x,fil)
fil.close()