import torch
import torch.nn as nn
import torch.optim as optim
from Networks import SVHN_FPN, BasicBlock
from utils import svhn_loaders, train_class_net

device = 'cuda:1'
print('device = ', device)

seed = 987
torch.manual_seed(seed)
save_dir = './results/'

# -----------------------------------------------------------------------------
# Network setup
# -----------------------------------------------------------------------------
num_blocks = [1, 1, 1]
contraction_factor = 0.9
lat_layers = 1
T = SVHN_FPN(lat_layers=lat_layers, num_channels=64,
             contraction_factor=contraction_factor, block=BasicBlock,
             num_blocks=num_blocks, architecture='Explicit').to(device)
num_classes = 10
eps = 1.0e-4
max_depth = 500

# -----------------------------------------------------------------------------
# Training settings
# -----------------------------------------------------------------------------
max_epochs = 100
learning_rate = 1.0e-4  # 5.0e-3
weight_decay = 2e-4
optimizer = optim.Adam(T.parameters(), lr=learning_rate,
                       weight_decay=weight_decay)
lr_scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=200, gamma=1.0)
checkpt_path = './models/'
loss = nn.CrossEntropyLoss()

# -----------------------------------------------------------------------------
# Load dataset
# -----------------------------------------------------------------------------
batch_size = 100
test_batch_size = 400
train_loader, test_loader = svhn_loaders(train_batch_size=batch_size,
                                         test_batch_size=test_batch_size)


# train network!
T = train_class_net(T, max_epochs, lr_scheduler, train_loader,
                    test_loader, optimizer, loss, num_classes,
                    eps, max_depth, save_dir=save_dir)
