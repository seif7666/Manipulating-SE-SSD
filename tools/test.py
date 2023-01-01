import argparse
import logging
import os
import os.path as osp
import shutil
import tempfile
import numpy
import pickle
import torch
import torch.distributed as dist
from det3d import torchie
from det3d.core import coco_eval, results2json
from det3d.datasets import  build_dataset
from det3d.datasets.kitti import kitti_common as kitti
from det3d.datasets.kitti.eval import get_official_eval_result
from det3d.datasets.utils.kitti_object_eval_python.evaluate import (evaluate as kitti_evaluate,)
from det3d.models import build_detector
from det3d.torchie.apis import init_dist
from det3d.torchie.apis.train import example_convert_to_torch
from det3d.torchie.parallel import MegDataParallel, MegDistributedDataParallel
from det3d.torchie.trainer import get_dist_info, load_checkpoint
from det3d.torchie.trainer.trainer import example_to_device
from det3d.utils.dist.dist_common import (all_gather, get_rank, get_world_size, is_main_process, synchronize,)
from tqdm import tqdm
from det3d.torchie.parallel import collate, collate_kitti
from torch.utils.data import DataLoader

def get_dataset_ids(mode='val'):
    assert mode in ['test', 'val', 'trainval', 'val']
    id_file_path = "../det3d/datasets/ImageSets/{}.txt".format(mode)
    with open(id_file_path, 'r') as f:
        ids = f.readlines()
    ids = list(map(int, ids))
    return ids


def test(dataloader, model, save_dir="", device="cuda", distributed=False,):
    if distributed:
        model = model.module
    dataset = dataloader.dataset         # det3d.datasets.kitti.kitti.KittiDataset
    device = torch.device(device)        # device(type='cuda')
    num_devices = get_world_size()       # 1

    detections = compute_on_dataset(model, dataloader, device)
    synchronize()
    predictions = _accumulate_predictions_from_multiple_gpus(detections)

    if not is_main_process(): # False
        return
    return dataset.evaluation(predictions, str(save_dir))


# todo: modified by zhengwu, to eval point cloud with assigned id on trained model with single gpu;
# todo: visulization of predicted and gt results;
# todo: visulization of feature maps generated by the network;
def test_v2(dataloader, model, device="cuda", distributed=False, eval_id=None, vis_id=None):
    '''
       example:
           python test_v2.py --eval_id 6 8 --vis_id 6
    '''
    # prepare model
    if distributed:
        model = model.module
    model.eval()

    # prepare samples
    kitti_dataset = dataloader.dataset         # det3d.datasets.kitti.kitti.KittiDataset
    valid_ids = get_dataset_ids('val')
    samples= []
    indices = numpy.random.randint(0,len(valid_ids),10,dtype=int)
    # print(indices)
    indices=[3566,1246,1308,1940,2462,216,1924,2117,1967,2351]
    # print(f'Valid IDs are: {valid_ids}')
    for id in indices:
        index = valid_ids.index(id)
        samples.append(kitti_dataset[index])
    batch_samples = collate_kitti(samples)
    example = example_to_device(batch_samples, device=torch.device(device))

    # evaluation
    results_dict = {}
    with torch.no_grad():
        # outputs: predicted results in lidar coord.
        outputs = model(example, return_loss=False, rescale=True)
        for output in outputs:
            token = output["metadata"]["token"]
            for k, v in output.items():
                if k not in ["metadata", ]:
                    output[k] = v.to(torch.device("cpu"))
            results_dict.update({token: output, })

        # pred_annos: convert predictions in lidar to cam coord.
        res_dir = os.path.join("./", "sample_eval_results")
        os.makedirs(res_dir, exist_ok=True)
        pred_annos = kitti_dataset.convert_detection_to_kitti_annos(results_dict, partial=True)

        # save predicted results to txt files.
        for dt in pred_annos:
            with open(os.path.join(res_dir, "%06d.txt" % int(dt["metadata"]["token"])), "w") as fout:
                lines = kitti.annos_to_kitti_label(dt)
                for line in lines:
                    fout.write(line + "\n")


    # visualization part
    # if vis_id is not None:
        # assert  vis_id in eval_id
    from det3d.kitti_visualization import kitti_object,show_lidar_with_boxes
    import numpy as np

    for index in indices:
        # index = eval_id.index(vis_id)
        pred_box_loc = pred_annos[index]['location']
        pred_box_dim = pred_annos[index]['dimensions']
        pred_box_ry  = pred_annos[index]['rotation_y'].reshape(-1, 1)
        pred_boxes = np.concatenate((pred_box_loc, pred_box_dim[:,[1,2,0]], pred_box_ry), axis=1)
        pred_scores = pred_annos[index]['score']

        index = valid_ids.index(vis_id)

        kitt= kitti_object("/content/drive/MyDrive/Graduation_Project/ObjectDetection3D/data_object_velodyne/")
        # lidar_data1 = kitt.get_lidar(vis_id, '/content/drive/MyDrive/Graduation_Project/ObjectDetection3D/data_object_velodyne/training/velodyne/000006.bin')
        # lidar_data2 = kitt.get_lidar(vis_id)
        # print(f'First is {np.sum(lidar_data1)}\t second is {np.sum(lidar_data2)}')
        # print(f'Esitmate Lidar sum is {torch.sum(lidar_data)}')
        # file = open('lidar.pkl', 'wb')
        # pickle.dump(lidar_data, file)
        # file.close()
        # print(f'Lidar shape is {lidar_data.shape}')
        # calib= kitt.get_calibration(vis_id)
        # print(calib.P)
        # file = open('calib.pkl', 'wb')
        # pickle.dump(calib, file)
        # file.close()
        file = open(f'pred_boxes_{vis_id}.pkl', 'wb')
        pickle.dump(pred_boxes, file)
        file.close()
        print('DOne!')
    # show_lidar_with_boxes(lidar_data,pred_boxes,calib)


        # print(f'Sample ID is {vis_id}')
        # print(f'pred_boxes3d {pred_boxes}')
        # print(f'Sample ID is {pred_scores}')

        # show_lidar_with_boxes_rect(
        #     sample_id=vis_id,
        #     pred_boxes3d=pred_boxes,
        #     pred_scores = pred_scores,
        # )


def compute_on_dataset(model, data_loader, device, timer=None, show=False):
    '''
        Get predictions by model inference.
            - output: ['box3d_lidar', 'scores', 'label_preds', 'metadata'];
            - detections: type: dict, length: 3769, keys: image_ids, detections[image_id] = output;
    '''
    model.eval()
    cpu_device = torch.device("cpu")

    results_dict = {}
    for i, batch in enumerate(data_loader):
        if i == 1:
            prog_bar = torchie.ProgressBar(len(data_loader.dataset) - 1)
        example = example_to_device(batch, device=device)
        with torch.no_grad():
            outputs = model(example, return_loss=False, rescale=not show)   # list_length=batch_size: 8
            for output in outputs:                   # output.keys(): ['box3d_lidar', 'scores', 'label_preds', 'metadata']
                token = output["metadata"]["token"]  # token should be the image_id
                for k, v in output.items():
                    if k not in ["metadata",]:
                        output[k] = v.to(cpu_device)
                results_dict.update({token: output,})
                if i >= 1:
                    prog_bar.update()

    return results_dict



def _accumulate_predictions_from_multiple_gpus(predictions_per_gpu):
    all_predictions = all_gather(predictions_per_gpu)
    if not is_main_process():
        return

    predictions = {}
    for p in all_predictions:
        predictions.update(p)

    return predictions

data_root = "/data/zhengwu"

def parse_args():
    parser = argparse.ArgumentParser(description="MegDet test detector")
    parser.add_argument("--config", default='../examples/second/configs/config.py', help="test config file path")
    parser.add_argument("--checkpoint", default='epoch_58.pth',  help="checkpoint file")
    parser.add_argument("--out", default='out.pkl', help="output result file")
    parser.add_argument("--json_out",  default='json_out.json', help="output result file name without extension", type=str)
    parser.add_argument("--eval", type=str, nargs="+", choices=["proposal", "proposal_fast", "bbox", "segm", "keypoints"], help="eval types",)
    parser.add_argument("--show", action="store_true", help="show results")
    parser.add_argument("--txt_result", default=True, help="save txt")
    parser.add_argument("--tmpdir", help="tmp dir for writing some results")
    parser.add_argument("--launcher", choices=["none", "pytorch", "slurm", "mpi"], default="none",help="job launcher",)
    parser.add_argument("--local_rank", type=int, default=0)
    parser.add_argument("--eval_id", nargs='+', type=int, default=None,)
    parser.add_argument("--vis_id", type=int, default=None, )
    args = parser.parse_args()
    if "LOCAL_RANK" not in os.environ:
        os.environ["LOCAL_RANK"] = str(args.local_rank)
    return args


def main():
    args = parse_args()
    print(args)
    assert args.out or args.show or args.json_out, ('Please specify at least one operation (save or show the results) with the argument "--out" or "--show" or "--json_out"')

    if args.out is not None and not args.out.endswith((".pkl", ".pickle")):
        raise ValueError("The output file must be a pkl file.")

    if args.json_out is not None and args.json_out.endswith(".json"):
        args.json_out = args.json_out[:-5]

    cfg = torchie.Config.fromfile(args.config)
    if cfg.get("cudnn_benchmark", False):  # False
        torch.backends.cudnn.benchmark = True

    # cfg.model.pretrained = None
    # cfg.data.test.test_mode = True
    cfg.data.val.test_mode = True

    # init distributed env first, since logger depends on the dist info.
    if args.launcher == "none":
        distributed = False
    else:
        distributed = True
        init_dist(args.launcher, **cfg.dist_params)

    # build the dataloader, TODO: support multiple images per gpu (only minor changes are needed)
    dataset = build_dataset(cfg.data.val)
    batch_size = cfg.data.samples_per_gpu
    num_workers = cfg.data.workers_per_gpu
    data_loader = DataLoader(dataset, batch_size=batch_size, sampler=None, num_workers=num_workers, collate_fn=collate_kitti, shuffle=False,)

    # build the model and load checkpoint
    model = build_detector(cfg.model, train_cfg=None, test_cfg=cfg.test_cfg)
    checkpoint_path = os.path.join(cfg.work_dir, args.checkpoint)
    checkpoint = load_checkpoint(model, checkpoint_path, map_location="cpu")

    # old versions did not save class info in checkpoints, this walkaround is for backward compatibility
    if "CLASSES" in checkpoint["meta"]:
        model.CLASSES = checkpoint["meta"]["CLASSES"]
    else:
        model.CLASSES = dataset.CLASSES

    model = MegDataParallel(model, device_ids=[0])
    if args.eval_id is None:
        result_dict, detections = test(data_loader, model, save_dir=None, distributed=distributed)

        # for k, v in result_dict["results"].items():
        #     print(f"Evaluation {k}: {v}")

        for k, v in result_dict["results"].items():
            print(f"Evaluation {k}: {v}")
            # f.write(f"\nEvaluation {k}: {v}\n")

        for k, v in result_dict["results_2"].items():
            print(f"Evaluation {k}: {v}")
            # f.write(f"\nEvaluation {k}: {v}\n")

        # save mAP results to out.pkl file.
        # rank, _ = get_dist_info()
        # if args.out and rank == 0:
        #     print("\nwriting results to {}".format(args.out))
        #     torchie.dump(detections, os.path.join(cfg.work_dir, args.out))

        # if args.txt_result:  # True
        #     res_dir = os.path.join(cfg.work_dir, "predictions")
        #     os.makedirs(res_dir, exist_ok=True)
        #     for dt in detections:
        #         with open(os.path.join(res_dir, "%06d.txt" % int(dt["metadata"]["token"])), "w") as fout:
        #             lines = kitti.annos_to_kitti_label(dt)
        #             for line in lines:
        #                 fout.write(line + "\n")

        #     gt_labels_dir = data_root + "/KITTI/object/training/label_2"
        #     label_split_file = data_root + "/KITTI/ImageSets/val.txt"
        #     # todo: this evaluation is different from previous one
        #     ap_result_str, ap_dict = kitti_evaluate(gt_labels_dir, res_dir, label_split_file=label_split_file, current_class=0,)
        #     print(ap_result_str)

    else:
        assert type(args.eval_id) is list
        test_v2(data_loader, model, distributed=distributed, eval_id=args.eval_id, vis_id=args.vis_id)



if __name__ == "__main__":
    main()
