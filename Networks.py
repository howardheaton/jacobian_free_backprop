import torch
import torch.nn as nn


class MNIST_FCN(nn.Module):
    def __init__(self, dim_out, dim_hid, hidden_layers, device):
        super().__init__()
        self.fc_d = nn.Linear(784,     dim_hid, bias=True)
        self.fc_m = nn.Linear(dim_hid, dim_hid, bias=False)
        self.fc_y = nn.Linear(dim_hid, dim_out, bias=True)
        self.fc_u = nn.Linear(dim_out, dim_out, bias=False)
        self.relu = nn.ReLU()
        self.project_weights(s_lo=1.0)

    def name(self):
        return 'MNIST-FCN'

    def forward(self, u, d=None):
        y = self.relu(self.fc_d(d.float()))
        y = self.relu(self.fc_m(y))
        return torch.abs(0.5 * self.fc_u(u.float()) + 0.5 * self.fc_y(y))

    def project_weights(self, s_lo=0.0):
        """ All linear maps must yield 1-Lipschitz operators,
            which is accomplished by bounding all singular values
            by unity.
        """
        self.fc_d.weight.data = self.proj_sing_val(self.fc_d.weight.data, s_lo)
        self.fc_m.weight.data = self.proj_sing_val(self.fc_m.weight.data, s_lo)
        self.fc_u.weight.data = self.proj_sing_val(self.fc_u.weight.data, s_lo)
        self.fc_y.weight.data = self.proj_sing_val(self.fc_y.weight.data, s_lo)

    def proj_sing_val(self, Ak, s_lo=0.0):
        """ Project singular values of matrices onto interval [s_low, 1.0].
        """
        u, s, v = torch.svd(Ak)
        s[s > 1.0] = 1.0
        s[s < s_lo] = s_lo
        return torch.mm(torch.mm(u, torch.diag(s)), v.t())


class MNIST_CNN(nn.Module):
    def __init__(self, hid_dim):
        super(MNIST_CNN, self).__init__()
        self.avgpool = nn.AvgPool2d(kernel_size=2)
        self.relu = nn.ReLU()
        self.fc_u = nn.Linear(hid_dim, hid_dim, bias=False)
        self.fc_y = nn.Linear(1750,    hid_dim, bias=False)
        self.project_weights(s_lo=1.0)
        self.conv1 = torch.nn.utils.spectral_norm(nn.Conv2d(in_channels=1,
                                                            out_channels=90,
                                                            kernel_size=3,
                                                            stride=1))
        self.conv2 = torch.nn.utils.spectral_norm(nn.Conv2d(in_channels=90,
                                                            out_channels=70,
                                                            kernel_size=3,
                                                            stride=1))

    def name(self):
        return 'MNIST-CNN'

    def forward(self, u, d):
        y = self.avgpool(self.relu(self.conv1(d)))
        y = self.avgpool(self.relu(self.conv2(y))).view(d.shape[0], -1)
        return torch.abs(0.1 * self.fc_u(u) + 0.9 * self.fc_y(y))

    def project_weights(self, s_lo=0.0):
        """ All linear maps must yield 1-Lipschitz operators,
            which is accomplished by bounding all singular values
            by unity.
        """
        self.fc_u.weight.data = self.proj_sing_val(self.fc_u.weight.data, s_lo)
        self.fc_y.weight.data = self.proj_sing_val(self.fc_y.weight.data, s_lo)

    def proj_sing_val(self, Ak, s_lo=0.0):
        """ Project singular values of matrices onto interval [s_low, 1.0].
        """
        u, s, v = torch.svd(Ak)
        s[s > 1.0] = 1.0
        s[s < s_lo] = s_lo
        return torch.mm(torch.mm(u, torch.diag(s)), v.t())