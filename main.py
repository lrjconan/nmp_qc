#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
    Trains a Neural Message Passing Model on various datasets. Methodologi defined in:

    Gilmer, J., Schoenholz S.S., Riley, P.F., Vinyals, O., Dahl, G.E. (2017)
    Neural Message Passing for Quantum Chemistry.
    arXiv preprint arXiv:1704.01212 [cs.LG]

"""

# Own Modules
import datasets
from models.model import Nmp
import LogMetric
from LogMetric import AverageMeter

# Torch
import torch
import torch.optim as optim
import torch.nn as nn
from torch.autograd import Variable

import time
import argparse
import os
import numpy as np

__author__ = "Pau Riba, Anjan Dutta"
__email__ = "priba@cvc.uab.cat, adutta@cvc.uab.cat"


# Parser check
def restricted_float(x):
    x = float(x)
    if x < 1e-5 or x > 5e-4:
        raise argparse.ArgumentTypeError("%r not in range [1e-5, 1e-4]"%(x,))
    return x

# Argument parser
parser = argparse.ArgumentParser(description='Neural message passing')

parser.add_argument('--dataset', default='qm9', help='QM9')
parser.add_argument('--datasetPath', default='./data/qm9/dsgdb9nsd/', help='dataset path')
# Optimization Options
parser.add_argument('--batch-size', type=int, default=20, metavar='N',
                    help='Input batch size for training (default: 20)')
parser.add_argument('--no-cuda', action='store_true', default=False,
                    help='Enables CUDA training')
parser.add_argument('--epochs', type=int, default=360, metavar='N',
                    help='Number of epochs to train (default: 360)')
parser.add_argument('--lr', type=restricted_float, default=1e-4, metavar='LR',
                    help='Initial learning rate [1e-5, 5e-4] (default: 1e-4)')
parser.add_argument('--lr-decay', type=restricted_float, default=0.6, metavar='LR-DECAY',
                    help='Learning rate decay factor [.01, 1] (default: 0.6)')
parser.add_argument('--momentum', type=float, default=0.9, metavar='M',
                    help='SGD momentum (default: 0.9)')
# i/o
parser.add_argument('--log-interval', type=int, default=10, metavar='N',
                    help='How many batches to wait before logging training status')

dtype = torch.FloatTensor


def main():
    global args
    args = parser.parse_args()

    # Check if CUDA is enabled
    args.cuda = not args.no_cuda and torch.cuda.is_available()

    # Load data
    root = args.datasetPath

    print('Prepare files')
    files = [f for f in os.listdir(root) if os.path.isfile(os.path.join(root, f))]

    idx = np.random.permutation(len(files))
    idx = idx.tolist()

    valid_ids = [files[i] for i in idx[0:10000]]
    test_ids = [files[i] for i in idx[10000:20000]]
    train_ids = [files[i] for i in idx[20000:]]

    data_train = datasets.Qm9(root, train_ids)
    data_valid = datasets.Qm9(root, valid_ids)
    data_test = datasets.Qm9(root, test_ids)

    # Define model and optimizer
    print('Define model')
    # Select one graph
    g_tuple, l = data_train[0]
    g, h_t, e = g_tuple

    print('\tStatistics')
    stat_dict = datasets.utils.get_graph_stats(data_valid, ['degrees', 'target_mean', 'target_std'])

    data_train.set_target_transform(lambda x: datasets.utils.normalize_data(x,stat_dict['target_mean'],
                                                                            stat_dict['target_std']))
    data_valid.set_target_transform(lambda x: datasets.utils.normalize_data(x, stat_dict['target_mean'],
                                                                            stat_dict['target_std']))
    data_test.set_target_transform(lambda x: datasets.utils.normalize_data(x, stat_dict['target_mean'],
                                                                            stat_dict['target_std']))

    # Data Loader
    train_loader = torch.utils.data.DataLoader(data_train,
                                               batch_size=20, shuffle=True, collate_fn=datasets.utils.collate_g)
    valid_loader = torch.utils.data.DataLoader(data_valid,
                                               batch_size=20, shuffle=True, collate_fn=datasets.utils.collate_g)
    test_loader = torch.utils.data.DataLoader(data_test,
                                               batch_size=20, shuffle=True, collate_fn=datasets.utils.collate_g)

    print('\tCreate model')
    model = Nmp(stat_dict['degrees'], [len(list(h_t.values())[0]), len(list(e.values())[0])], [25, 30, 35], len(l))

    print('Check cuda')
    #if args.cuda:
    #    model.cuda()

    print('Optimizer')
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.MSELoss()

    # Epoch for loop
    for epoch in range(1, args.epochs + 1):
        if epoch in args.schedule:
            state['learning_rate'] *= args.gamma
            for param_group in optimizer.param_groups:
                param_group['lr'] = state['learning_rate']

        # train for one epoch
        train(train_loader, model, criterion, optimizer, epoch)

        # evaluate on validation set
        validate(valid_loader, model, criterion)


def train(train_loader, model, criterion, optimizer, epoch):
    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    error_ratio = AverageMeter()

    # switch to train mode
    model.train()

    end = time.time()
    for i, batch in enumerate(train_loader):

        # measure data loading time
        data_time.update(time.time() - end)

        train_loss = Variable(torch.zeros(1, 1))

        # Iterate batch
        for (input_var, target) in batch:
            target_var = torch.autograd.Variable(dtype(target))

            # compute output
            output = model(input_var)
            loss = criterion(output, target_var)
            train_loss += loss

            # Logs
            losses.update(loss.data[0])
            error_ratio.update(LogMetric.error_ratio(output.data.numpy(), target))

        # compute gradient and do SGD step
        optimizer.zero_grad()
        train_loss.backward()
        optimizer.step()

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.log_interval == 0:
            print('Epoch: [{0}][{1}/{2}]\t'
                  'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Error Ratio {err.val:.4f} ({err.avg:.4f})'
                  .format(epoch, i, len(train_loader), batch_time=batch_time,
                          data_time=data_time, loss=losses, err=error_ratio))


def validate(val_loader, model, criterion):
    batch_time = AverageMeter()
    losses = AverageMeter()
    error_ratio = AverageMeter()

    # switch to evaluate mode
    model.eval()

    end = time.time()
    for i, batch in enumerate(val_loader):

        train_loss = Variable(torch.zeros(1, 1))

        # Iterate batch
        for (input_var, target) in batch:
            target_var = torch.autograd.Variable(dtype(target))

            # compute output
            output = model(input_var)
            loss = criterion(output, target_var)
            train_loss += loss

            # Logs
            losses.update(loss.data[0])
            error_ratio.update(LogMetric.error_ratio(output.data.numpy(), target))

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.log_interval == 0:
            print('Test: [{0}/{1}]\t'
                  'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Error Ratio {err.val:.4f} ({err.avg:.4f})'
                  .format(i, len(val_loader), batch_time=batch_time,
                          loss=losses, err=error_ratio))

    print(' * Average Error Ratio {err.avg:.3f}'
          .format(err=error_ratio))


if __name__ == '__main__':
    main()
