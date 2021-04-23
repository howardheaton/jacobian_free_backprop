import torch
import torch.nn               as nn
import torch.optim            as optim
import torchvision.transforms as transforms
from torch.utils.data         import Dataset, TensorDataset, DataLoader
from torchvision              import datasets
from torch.optim.lr_scheduler import StepLR
from prettytable import PrettyTable
import time
import numpy as np
from BatchCG import cg_batch
from time import sleep
import time
from tqdm import tqdm

import Networks
from FPN import FPN



device = "cuda:1" 
seed   = 43
torch.manual_seed(seed)


class MNIST_CNN(nn.Module):
    def __init__(self, lat_dim, device, s_hi=1.0):
        super().__init__()
        self.maxpool = nn.MaxPool2d(kernel_size=2)
        self.relu = nn.ReLU()
        self.fc_y = nn.Linear(1000,    lat_dim, bias=True)
        self.fc_u = nn.Linear(lat_dim, lat_dim, bias=False)
        self.fc_f = nn.Linear(lat_dim, 10, bias=False)
        self._lat_dim = lat_dim
        self._device = device
        self._s_hi = s_hi
        self.drop_out = nn.Dropout(p=0.5)
        self.soft_max = nn.Softmax(dim=1)
        self.conv1 = nn.Conv2d(in_channels=1,
                               out_channels=96,
                               kernel_size=3,
                               stride=1)
        self.conv2 = nn.Conv2d(in_channels=96,
                               out_channels=40,
                               kernel_size=3,
                               stride=1)

    def forward(self, u, Qd):
        return self.latent_space_forward(u, Qd)

    def name(self):
        return 'MNIST_CNN'

    def device(self):
        return self._device

    def lat_dim(self):
        return self._lat_dim

    def s_hi(self):
        return self._s_hi

    def latent_space_forward(self, u, v):
        return self.relu(self.fc_u(0.99 * u + v))

    def data_space_forward(self, d):
        v = self.maxpool(self.relu(self.drop_out(self.conv1(d))))
        v = self.maxpool(self.relu(self.drop_out(self.conv2(v))))
        v = v.view(d.shape[0], -1)
        return self.relu(self.fc_y(v))

    def map_latent_to_inference(self, u):
        return self.fc_f(u)

    def bound_lipschitz_constants(self):
        for mod in self.modules():
            if type(mod) == nn.Linear:
                is_lat_space_op = mod.weight.data.size()[0] == self.lat_dim() \
                                and mod.weight.data.size()[1] == self.lat_dim()
                s_hi = 1.0 if is_lat_space_op else self.s_hi()
                svd_attempts = 0
                compute_svd = False
                while not compute_svd and svd_attempts < 10:
                    try:
                        u, s, v = torch.svd(mod.weight.data)
                        compute_svd = True
                    except RuntimeError as e:
                        if 'SBDSDC did not converge' in str(e):
                            print('\nWarning: torch.svd() did not converge. ' +
                                  'Adding Gaussian noise and retrying.\n')
                            mat_size = mod.weight.data.size()
                            # print('mod.weight.data.device = ', mod.weight.data.device)
                            mod.weight.data += 1.0e-2 * torch.randn(mat_size, device=self.device)
                            svd_attempts += 1
                s[s > s_hi] = s_hi
                mod.weight.data = torch.mm(torch.mm(u, torch.diag(s)), v.t())

#-------------------------------------------------------------------------------
# Load dataset
#-------------------------------------------------------------------------------
batch_size = 50
test_batch_size = 2000
train_loader = torch.utils.data.DataLoader(
                        datasets.MNIST('data',
                                    train=True,
                                    download=True,
                                    transform=transforms.Compose([
                                        transforms.ToTensor(),
                                        transforms.Normalize((0.1307,), (0.3081,))
                                    ])),
                        batch_size=batch_size,
                        shuffle=True)

test_loader = torch.utils.data.DataLoader(
                        datasets.MNIST('data',
                                    train=False,
                                    transform=transforms.Compose([
                                        transforms.ToTensor(),
                                        transforms.Normalize((0.1307,), (0.3081,))
                                    ])),
                        batch_size=test_batch_size,
                        shuffle=False)

#-------------------------------------------------------------------------------
# Compute fixed point
#-------------------------------------------------------------------------------
def compute_fixed_point(T, Qd, max_depth, device):

        # bound lipschitz constants:
        if T.training:
          T.bound_lipschitz_constants()

        T.eval()
        depth = 0.0
        u = torch.zeros(Qd.shape[0], T.lat_dim(), device = device)
        u_prev = u.clone()
        indices = np.array(range(len(u[:, 0])))
        
        with torch.no_grad():
            all_samp_conv = False
            while not all_samp_conv and depth < max_depth:
                u_prev = u.clone()
                u = T.latent_space_forward(u, Qd)
                depth += 1.0
                all_samp_conv = torch.max(torch.norm(u - u_prev, dim=1)) <= eps
        # if depth >= max_depth:c
            # print("\nWarning: Max Depth Reached - Break Forward Loop\n")

        return u, depth

#-------------------------------------------------------------------------------
# Compute testing statistics
#-------------------------------------------------------------------------------
def get_test_stats(net, data_loader, criterion, num_classes, eps, max_depth):
	test_loss = 0
	correct = 0
	net.eval()
	with torch.no_grad():
		for d_test, labels in test_loader:
			labels = labels.to(net.device())
			d_test = d_test.to(net.device())
			batch_size = d_test.shape[0]

			ut = torch.zeros((d_test.shape[0], num_classes), device=device)
			for i in range(d.size()[0]):
			    ut[i, labels[i].cpu().numpy()] = 1.0

			Qd = net.data_space_forward(d_test)
			y, depth = compute_fixed_point(net, Qd, max_depth, device)

			phi_Tu = net.map_latent_to_inference(y)
			# output  = criterion(phi_Tu, labels)
			output = criterion(phi_Tu.double(), ut.double())

			test_loss += batch_size * output.item()

			pred = phi_Tu.argmax(dim=1, keepdim=True)
			correct += pred.eq(labels.view_as(pred)).sum().item()

	test_loss /= len(test_loader.dataset)
	test_acc = 100. * correct/len(test_loader.dataset)

	return test_loss, test_acc, correct, depth

#-------------------------------------------------------------------------------
# Network setup
#-------------------------------------------------------------------------------
inf_dim     = 10  # dimension of signal space
lat_dim     = 46
s_hi        = 1.0
T           = MNIST_CNN(lat_dim, device, s_hi=s_hi).to(device)
num_classes = 10
eps = 1.0e-6
max_depth = 500

#-------------------------------------------------------------------------------
# Training settings
#-------------------------------------------------------------------------------
max_epochs    = 200
learning_rate = 5.0e-5 #1.0e-4
optimizer     = optim.Adam(T.parameters(), lr=learning_rate)
lr_scheduler  = optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=0.98)
criterion     = nn.MSELoss()

def num_params(model):
    table = PrettyTable(["Modules", "Parameters"])
    num_params = 0
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad: continue
        table.add_row([name, parameter.numel()])
        num_params += parameter.numel()
    print(table)
    print(f"Total Trainable Params: {num_params}")
    return num_params


avg_time      = 0.0         # saves average time per epoch
total_time    = 0.0
time_hist     = []
n_Umatvecs    = []          
max_iter_cg   = 500
tol_cg        = eps
save_dir = 'MNIST_CNNAdjoint_tolcg1e-6_eps1e-6_saved_weights.pth';

# save histories for testing data set
test_loss_hist   = [] # test loss history array
test_acc_hist    = [] # test accuracy history array
depth_test_hist  = [] # test depths history array
train_loss_hist  = [] # train loss history array
train_acc_hist   = [] # train accuracy history array

# start_time_epoch = time.time() # timer for display execution time per epoch multiple
fmt        = '[{:4d}/{:4d}]: train acc = {:5.2f}% | train_loss = {:7.3e} | ' 
fmt       += ' test acc = {:5.2f}% | test loss = {:7.3e} | '
fmt       += 'depth = {:5.1f} | lr = {:5.1e} | time = {:4.1f} sec | n_Umatvecs = {:4d}'
print(T)                 # display Tnet configuration
num_params(T)            # display Tnet parameters
print('\nTraining Fixed Point Network')
print('device = ', device)

best_test_acc = 0.0
#-------------------------------------------------------------------------------
# Execute Training
#-------------------------------------------------------------------------------
for epoch in range(max_epochs): 

    sleep(0.5)  # slows progress bar so it won't print on multiple lines
    tot = len(train_loader)
    temp_n_Umatvecs = 0
    start_time_epoch = time.time() 
    temp_max_depth = 0
    loss_ave = 0.0
    train_acc = 0.0
    with tqdm(total=tot, unit=" batch", leave=False, ascii=True) as tepoch:
      
        for idx, (d, labels) in enumerate(train_loader):         
            labels  = labels.to(device); d = d.to(device)

            ut = torch.zeros((d.size()[0], num_classes), device=device)
            for i in range(d.size()[0]):
                ut[i, labels[i].cpu().numpy()] = 1.0

            #-----------------------------------------------------------------------
            # Find Fixed Point
            #----------------------------------------------------------------------- 
            train_batch_size = d.shape[0] # re-define if batch size changes
            u0 = torch.zeros((train_batch_size, lat_dim)).to(device)
            with torch.no_grad():
                Qd = T.data_space_forward(d)
                u, depth = compute_fixed_point(T, Qd, max_depth, device)

                temp_max_depth = max(depth, temp_max_depth)

            #-----------------------------------------------------------------------
            # Adjoint Backprop 
            #-----------------------------------------------------------------------  
            T.train()
            optimizer.zero_grad() # Initialize gradient to zero

            # compute output for backprop
            u.requires_grad=True
            Qd = T.data_space_forward(d)
            Tu = T(u, Qd)
            phi_Tu = T.map_latent_to_inference(Tu)
            # output  = criterion(phi_Tu, labels)
            output = criterion(phi_Tu.double(), ut.double())
            train_loss = output.detach().cpu().numpy() * train_batch_size
            loss_ave += train_loss

            # compute rhs: = J * dldu = J * dl/dphi * dphi/du
            dldu    = torch.autograd.grad(outputs = output, inputs = Tu, 
                                        retain_graph=True, create_graph = True, only_inputs=True)[0];
            dldu    = dldu.detach() # note: dldu here = dl/dphi * dphi/du
            v       = torch.ones(train_batch_size, lat_dim, device=device)
            v.requires_grad=True
            dTdu_mv  = torch.autograd.grad(outputs=Tu, inputs = u, grad_outputs=v, retain_graph=True, create_graph = True, only_inputs=True)[0];
            JTv = v - dTdu_mv

            # trick for computing Jacobian-vector product using vector-Jacobian products
            # i.e., dT/du * v = JT * v => dJTv/dv * rhs = J * rhs
            rhs     = torch.autograd.grad(outputs = JTv, inputs = v, grad_outputs = dldu.detach(), 
                                                    retain_graph=True, create_graph = True, only_inputs=True)[0];
            rhs = rhs.detach()
            rhs = rhs.unsqueeze(2)

            v.requres_grad=False

            #-----------------------------------------------------------------------
            # Define JTJ matvec function
            #-----------------------------------------------------------------------
            def JTJ_matvec(v, u=u, Tu=Tu):
                # inputs:
                # v = vector to be multiplied by U = I - alpha*DS - (1-alpha)*DT) requires grad
                # u = fixed point vector u (should be untracked and vectorized!) requires grad
                # Tu = T applied to u (requires grad)

                # assumes one rhs: x (n_samples, n_dim, n_rhs) -> (n_samples, n_dim)

                v = v.squeeze(2)
                v.requires_grad=True
                # dTu/du * v = JT * v
                WTmv = torch.autograd.grad(outputs = Tu, inputs = u, grad_outputs = v, retain_graph=True, create_graph = True, only_inputs=True)[0]

                # d(dTu/du * v)/dv * (JT*v) = J * (JT*v)
                WWTmv = torch.autograd.grad(outputs = WTmv, inputs = v, grad_outputs = WTmv.detach(), retain_graph=True, create_graph = True, only_inputs=True)[0]
                v = v.detach()
                WTmv = WTmv.detach()
                Amv = WWTmv.unsqueeze(2).detach() 
                return Amv + 1e-3*v.unsqueeze(2)

            JTJinv_v, info = cg_batch(JTJ_matvec, rhs, M_bmm=None, X0=None, rtol=0, atol=tol_cg, maxiter=max_iter_cg, verbose=False)
            JTJinv_v = JTJinv_v.squeeze(2) # Uinv_v has size (batch_size x 10)

            temp_n_Umatvecs += info['niter'] * train_batch_size

            # compute dTdtheta
            Tu.backward(JTJinv_v)

            u.requires_grad=False
            v.requires_grad=False

            # update T parameters
            optimizer.step()     

            # -------------------------------------------------------------
            # Output training stats
            # -------------------------------------------------------------
            pred = phi_Tu.argmax(dim=1, keepdim=True)
            correct = pred.eq(labels.view_as(pred)).sum().item()
            train_acc = 0.99 * train_acc + 1.00 * correct / train_batch_size
            tepoch.update(1)
            tepoch.set_postfix(train_loss="{:5.2e}".format(train_loss
                                / train_batch_size),
                                train_acc="{:5.2f}%".format(train_acc),
                                depth="{:5.1f}".format(temp_max_depth))
            
    loss_ave /= len(train_loader.dataset)

    # update optimization scheduler
    lr_scheduler.step()

    # compute test loss and accuracy
    test_loss, test_acc, correct, depth_test = get_test_stats(T, test_loader, criterion, num_classes, eps, max_depth)

    end_time_epoch = time.time()
    time_epoch = end_time_epoch - start_time_epoch

    #---------------------------------------------------------------------------
    # Compute costs and statistics
    #---------------------------------------------------------------------------
    time_hist.append(time_epoch)
    total_time += time_epoch 
    avg_time /= total_time/(epoch+1)
    n_Umatvecs.append(temp_n_Umatvecs)

    test_loss_hist.append(test_loss)
    test_acc_hist.append(test_acc)
    train_loss_hist.append(loss_ave)
    train_acc_hist.append(train_acc)
    depth_test_hist.append(depth_test)

    #---------------------------------------------------------------------------
    # Print outputs to console
    #---------------------------------------------------------------------------

    print(fmt.format(epoch+1, max_epochs, train_acc, loss_ave,
                    test_acc, test_loss, temp_max_depth,
                    optimizer.param_groups[0]['lr'],
                    time_epoch, temp_n_Umatvecs))

    # ---------------------------------------------------------------------
    # Save weights 
    # ---------------------------------------------------------------------
    if test_acc > best_test_acc:
        best_test_acc = test_acc
        state = {
            'test_loss_hist': test_loss_hist,
            'test_acc_hist': test_acc_hist,
            'T_state_dict': T.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'lr_scheduler': lr_scheduler
        }
        file_name = save_dir + 'FPN_' + T.name() + '_weights.pth'
        torch.save(state, file_name)
        print('Model weights saved to ' + file_name)

    # ---------------------------------------------------------------------
    # Save history at last epoch
    # ---------------------------------------------------------------------
    if epoch+1 == max_epochs:
        state = {
            'test_loss_hist': test_loss_hist,
            'test_acc_hist': test_acc_hist,
            'train_loss_hist': train_loss_hist,
            'train_acc_hist': train_acc_hist,
            'optimizer_state_dict': optimizer.state_dict(),
            'lr_scheduler': lr_scheduler,
            'avg_time': avg_time, 
            'n_Umatvecs': n_Umatvecs,
            'time_hist': time_hist,
            'tol_cg': tol_cg,
            'eps': eps,
            'T_state_dict': T.state_dict(),
            'test_loss_hist': test_loss_hist,
            'test_acc_hist': test_acc_hist,
            'depth_test_hist': depth_test_hist
        }
        file_name = save_dir + 'FPN_' + T.name() + '_history.pth'
        torch.save(state, file_name)
        print('Training history saved to ' + file_name)
