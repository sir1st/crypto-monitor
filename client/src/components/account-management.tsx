import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/queryClient";
import { Account, InsertAccount } from "@shared/schema";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { motion } from "framer-motion";
import { 
  Plus, 
  Wallet, 
  Settings, 
  ShieldCheck,
  ExternalLink, 
  Check, 
  AlertCircle,
  Trash2
} from "lucide-react";

/** Shape returned by GET /api/accounts: credentials are stripped server-side. */
type AccountSummary = Omit<Account, "apiKey" | "apiSecret" | "passphrase"> & {
  hasCredentials: boolean;
  hasPassphrase: boolean;
};

export default function AccountManagement() {
  const queryClient = useQueryClient();
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [newAccount, setNewAccount] = useState<Omit<InsertAccount, 'userId'>>({
    name: '',
    exchange: 'bybit',
    apiKey: '',
    apiSecret: '',
    passphrase: '',
    status: 'active'
  });
  const [editingAccount, setEditingAccount] = useState<AccountSummary | null>(null);
  const [editForm, setEditForm] = useState({
    name: '',
    exchange: 'bybit',
    status: 'active',
    apiKey: '',
    apiSecret: '',
    passphrase: '',
  });

  // Fetch accounts from API
  const { data: accounts = [], isLoading, error } = useQuery<AccountSummary[]>({
    queryKey: ['/api/accounts'],
    queryFn: async () => {
      const response = await apiRequest('GET', '/api/accounts');
      return response.json();
    },
  });

  // Create account mutation
  const createAccountMutation = useMutation({
    mutationFn: async (accountData: Omit<InsertAccount, 'userId'>) => {
      const response = await apiRequest('POST', '/api/accounts', accountData);
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['/api/accounts'] });
      setNewAccount({ name: '', exchange: 'bybit', apiKey: '', apiSecret: '', passphrase: '', status: 'active' });
      setIsAddDialogOpen(false);
    },
  });

  // Delete account mutation
  const deleteAccountMutation = useMutation({
    mutationFn: async (accountId: number) => {
      await apiRequest('DELETE', `/api/accounts/${accountId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['/api/accounts'] });
    },
  });

  const handleAddAccount = () => {
    if (!newAccount.name || !newAccount.apiKey || !newAccount.apiSecret) {
      return;
    }
    createAccountMutation.mutate(newAccount);
  };

  // Update account mutation
  const updateAccountMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Record<string, unknown> }) => {
      const response = await apiRequest('PUT', `/api/accounts/${id}`, data);
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['/api/accounts'] });
      setEditingAccount(null);
    },
  });

  const handleRemoveAccount = (id: number) => {
    deleteAccountMutation.mutate(id);
  };

  const openEditAccount = (account: AccountSummary) => {
    setEditForm({
      name: account.name,
      exchange: account.exchange,
      status: account.status,
      apiKey: '',
      apiSecret: '',
      passphrase: '',
    });
    setEditingAccount(account);
  };

  const handleUpdateAccount = () => {
    if (!editingAccount || !editForm.name.trim()) return;
    const data: Record<string, unknown> = {
      name: editForm.name,
      exchange: editForm.exchange,
      status: editForm.status,
    };
    // Blank credential fields mean "keep what is already stored".
    if (editForm.apiKey) data.apiKey = editForm.apiKey;
    if (editForm.apiSecret) data.apiSecret = editForm.apiSecret;
    if (editForm.passphrase) data.passphrase = editForm.passphrase;
    updateAccountMutation.mutate({ id: editingAccount.id, data });
  };

  const getStatusColor = (status: Account['status']) => {
    switch (status) {
      case 'active': return 'bg-green-500/20 text-green-400';
      case 'inactive': return 'bg-yellow-500/20 text-yellow-400';
      case 'error': return 'bg-red-500/20 text-red-400';
      default: return 'bg-gray-500/20 text-gray-400';
    }
  };

  const getStatusIcon = (status: Account['status']) => {
    switch (status) {
      case 'active': return <Check className="h-3 w-3" />;
      case 'inactive': return <AlertCircle className="h-3 w-3" />;
      case 'error': return <AlertCircle className="h-3 w-3" />;
      default: return null;
    }
  };

  const getExchangeBadge = (exchange: string) => {
    switch (exchange.toLowerCase()) {
      case 'binance':
        return <Badge className="bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 uppercase text-[10px]">Binance</Badge>;
      case 'okx':
        return <Badge className="bg-white/15 text-white border border-white/20 uppercase text-[10px]">OKX</Badge>;
      case 'bybit':
        return <Badge className="bg-orange-500/20 text-orange-400 border border-orange-500/30 uppercase text-[10px]">Bybit</Badge>;
      case 'bitget':
        return <Badge className="bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 uppercase text-[10px]">Bitget</Badge>;
      case 'gate':
        return <Badge className="bg-blue-500/20 text-blue-400 border border-blue-500/30 uppercase text-[10px]">Gate.io</Badge>;
      default:
        return <Badge variant="outline" className="text-[10px]">{exchange}</Badge>;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active':
        return <Badge className="bg-green-600 text-white">Active</Badge>;
      case 'inactive':
        return <Badge variant="secondary">Inactive</Badge>;
      case 'error':
        return <Badge variant="destructive">Error</Badge>;
      default:
        return <Badge variant="outline">Unknown</Badge>;
    }
  };

  if (isLoading) {
    return (
      <Card className="bg-[#0d2538] border-[#00b4d8]/20">
        <CardHeader>
          <CardTitle className="text-lg font-bold text-white flex items-center">
            <Wallet className="h-5 w-5 text-[#00b4d8] mr-2" />
            Account Management
          </CardTitle>
          <CardDescription className="text-white/70">
            Loading accounts...
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="bg-[#0d2538] border-[#00b4d8]/20">
        <CardHeader>
          <CardTitle className="text-lg font-bold text-white flex items-center">
            <Wallet className="h-5 w-5 text-[#00b4d8] mr-2" />
            Account Management
          </CardTitle>
          <CardDescription className="text-red-400">
            Error loading accounts
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card className="bg-[#0d2538] border-[#00b4d8]/20">
      <CardHeader>
        <div className="flex justify-between items-start">
          <div>
            <CardTitle className="text-lg font-bold text-white flex items-center">
              <Wallet className="h-5 w-5 text-[#00b4d8] mr-2" />
              Account Management
            </CardTitle>
            <CardDescription className="text-white/70">
              Manage multiple exchange accounts and API connections
            </CardDescription>
          </div>
          <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
            <DialogTrigger asChild>
              <Button 
                variant="outline"
                size="sm"
                className="border-[#00b4d8]/50 text-[#00b4d8] hover:bg-[#00b4d8]/10"
              >
                <Plus className="h-4 w-4 mr-1" />
                Add Account
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-[#0d2538] border-[#00b4d8]/20 text-white">
              <DialogHeader>
                <DialogTitle className="text-[#ffc107]">Add New Exchange Account</DialogTitle>
                <DialogDescription className="text-white/70">
                  Connect a new exchange account to monitor additional positions and wallets.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 mt-4">
                <div className="space-y-2">
                  <Label htmlFor="accountName" className="text-white/80">Account Name</Label>
                  <Input
                    id="accountName"
                    placeholder="My Trading Account"
                    value={newAccount.name}
                    onChange={(e) => setNewAccount(prev => ({ ...prev, name: e.target.value }))}
                    className="bg-[#0a192f] border-[#00b4d8]/20 text-white"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="exchange" className="text-white/80">Exchange (交易所)</Label>
                  <select
                    id="exchange"
                    value={newAccount.exchange}
                    onChange={(e) => setNewAccount(prev => ({ ...prev, exchange: e.target.value as any }))}
                    className="w-full bg-[#0a192f] border border-[#00b4d8]/20 rounded-md px-3 py-2 text-white"
                  >
                    <option value="bybit">Bybit</option>
                    <option value="binance">Binance (币安)</option>
                    <option value="okx">OKX (欧易)</option>
                    <option value="bitget">Bitget</option>
                    <option value="gate">Gate.io (芝麻开门)</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="apiKey" className="text-white/80">API Key</Label>
                  <Input
                    id="apiKey"
                    placeholder="Enter your API key"
                    value={newAccount.apiKey}
                    onChange={(e) => setNewAccount(prev => ({ ...prev, apiKey: e.target.value }))}
                    className="bg-[#0a192f] border-[#00b4d8]/20 text-white"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="apiSecret" className="text-white/80">API Secret</Label>
                  <Input
                    id="apiSecret"
                    type="password"
                    placeholder="Enter your API secret"
                    value={newAccount.apiSecret}
                    onChange={(e) => setNewAccount(prev => ({ ...prev, apiSecret: e.target.value }))}
                    className="bg-[#0a192f] border-[#00b4d8]/20 text-white"
                  />
                </div>
                {(newAccount.exchange === 'okx' || newAccount.exchange === 'bitget') && (
                  <div className="space-y-2">
                    <Label htmlFor="passphrase" className="text-white/80">API Passphrase (密码)</Label>
                    <Input
                      id="passphrase"
                      type="password"
                      placeholder="Enter your API Passphrase"
                      value={newAccount.passphrase ?? ''}
                      onChange={(e) => setNewAccount(prev => ({ ...prev, passphrase: e.target.value }))}
                      className="bg-[#0a192f] border-[#00b4d8]/20 text-white"
                    />
                  </div>
                )}
                <div className="bg-[#0a192f]/50 p-3 rounded-md border border-[#00b4d8]/10">
                  <div className="flex items-start gap-2">
                    <AlertCircle className="h-4 w-4 text-[#ffc107] mt-0.5" />
                    <div className="text-xs text-white/70">
                      <p className="font-medium text-[#ffc107] mb-1">Security Notice</p>
                      <p>Only use API keys with read-only permissions. Never share keys that allow trading or withdrawals.</p>
                    </div>
                  </div>
                </div>
                <div className="flex gap-2 pt-4">
                  <Button 
                    onClick={handleAddAccount}
                    className="flex-1 bg-[#00b4d8] hover:bg-[#00b4d8]/80 text-white"
                  >
                    Add Account
                  </Button>
                  <Button 
                    onClick={() => setIsAddDialogOpen(false)}
                    variant="outline"
                    className="border-[#00b4d8]/50 text-[#00b4d8] hover:bg-[#00b4d8]/10"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {accounts.map((account, index) => (
            <motion.div
              key={account.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: index * 0.1 }}
            >
              <div className="bg-[#0a192f]/50 p-4 rounded-lg border border-[#00b4d8]/10 hover:border-[#00b4d8]/30 transition-colors">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center space-x-3 mb-2">
                      <h3 className="text-white font-medium">{account.name}</h3>
                      {getExchangeBadge(account.exchange)}
                      <Badge 
                        variant="outline" 
                        className={`text-xs ${getStatusColor(account.status)} border-current`}
                      >
                        <div className="flex items-center space-x-1">
                          {getStatusIcon(account.status)}
                          <span className="capitalize">{account.status}</span>
                        </div>
                      </Badge>
                    </div>
                    
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                      <div>
                        <div className="flex items-center space-x-2 text-white/70 mb-1">
                          <ExternalLink className="h-3 w-3" />
                          <span>Exchange: {account.exchange.charAt(0).toUpperCase() + account.exchange.slice(1)}</span>
                        </div>
                        <div className="flex items-center space-x-2 text-white/70">
                          {account.hasCredentials ? (
                            <>
                              <ShieldCheck className="h-3 w-3 text-green-400" />
                              <span>Credentials stored (read-only, never exposed)</span>
                            </>
                          ) : (
                            <>
                              <AlertCircle className="h-3 w-3 text-red-400" />
                              <span className="text-red-400">No credentials</span>
                            </>
                          )}
                        </div>
                      </div>
                      
                      <div>
                        <div className="text-white/70 text-xs">
                          Last Sync: {account.lastSync ? new Date(account.lastSync).toLocaleString() : 'Never'}
                        </div>
                      </div>
                    </div>
                  </div>
                  
                  <div className="flex items-center space-x-2 ml-4">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEditAccount(account)}
                      className="text-[#00b4d8] hover:bg-[#00b4d8]/10 p-2"
                      aria-label={`Edit ${account.name}`}
                    >
                      <Settings className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRemoveAccount(account.id)}
                      className="text-red-400 hover:bg-red-400/10 p-2"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </div>
            </motion.div>
          ))}
          
          {accounts.length === 0 && (
            <div className="text-center py-8 space-y-4">
              <div className="bg-[#0a192f]/50 p-6 rounded-lg border border-[#00b4d8]/10">
                <Wallet className="h-12 w-12 text-[#00b4d8]/50 mx-auto mb-3" />
                <h3 className="text-white font-medium mb-2">No Accounts Connected</h3>
                <p className="text-white/70 text-sm mb-4">
                  Add your first exchange account to start monitoring positions
                </p>
                <Button 
                  onClick={() => setIsAddDialogOpen(true)}
                  className="bg-[#00b4d8] hover:bg-[#00b4d8]/80 text-white"
                >
                  <Plus className="h-4 w-4 mr-1" />
                  Add Account
                </Button>
              </div>
            </div>
          )}
        </div>

        <Dialog
          open={editingAccount !== null}
          onOpenChange={(open) => {
            if (!open) setEditingAccount(null);
          }}
        >
          <DialogContent className="bg-[#0d2538] border-[#00b4d8]/20 text-white">
            <DialogHeader>
              <DialogTitle className="text-[#ffc107]">Edit {editingAccount?.name}</DialogTitle>
              <DialogDescription className="text-white/70">
                Update the label, status or credentials. Leave a credential field blank to keep the stored value.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 mt-4">
              <div className="space-y-2">
                <Label htmlFor="editName" className="text-white/80">Account Name</Label>
                <Input
                  id="editName"
                  value={editForm.name}
                  onChange={(e) => setEditForm(prev => ({ ...prev, name: e.target.value }))}
                  className="bg-[#0a192f] border-[#00b4d8]/20 text-white"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="editExchange" className="text-white/80">Exchange (交易所)</Label>
                <select
                  id="editExchange"
                  value={editForm.exchange}
                  onChange={(e) => setEditForm(prev => ({ ...prev, exchange: e.target.value }))}
                  className="w-full bg-[#0a192f] border border-[#00b4d8]/20 rounded-md px-3 py-2 text-white"
                >
                  <option value="bybit">Bybit</option>
                  <option value="binance">Binance (币安)</option>
                  <option value="okx">OKX (欧易)</option>
                  <option value="bitget">Bitget</option>
                  <option value="gate">Gate.io (芝麻开门)</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="editStatus" className="text-white/80">Status</Label>
                <select
                  id="editStatus"
                  value={editForm.status}
                  onChange={(e) => setEditForm(prev => ({ ...prev, status: e.target.value }))}
                  className="w-full bg-[#0a192f] border border-[#00b4d8]/20 rounded-md px-3 py-2 text-white"
                >
                  <option value="active">Active</option>
                  <option value="inactive">Inactive</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="editApiKey" className="text-white/80">API Key</Label>
                <Input
                  id="editApiKey"
                  type="password"
                  placeholder="Leave blank to keep current"
                  value={editForm.apiKey}
                  onChange={(e) => setEditForm(prev => ({ ...prev, apiKey: e.target.value }))}
                  className="bg-[#0a192f] border-[#00b4d8]/20 text-white"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="editApiSecret" className="text-white/80">API Secret</Label>
                <Input
                  id="editApiSecret"
                  type="password"
                  placeholder="Leave blank to keep current"
                  value={editForm.apiSecret}
                  onChange={(e) => setEditForm(prev => ({ ...prev, apiSecret: e.target.value }))}
                  className="bg-[#0a192f] border-[#00b4d8]/20 text-white"
                />
              </div>
              {(editForm.exchange === 'okx' || editForm.exchange === 'bitget') && (
                <div className="space-y-2">
                  <Label htmlFor="editPassphrase" className="text-white/80">API Passphrase (密码)</Label>
                  <Input
                    id="editPassphrase"
                    type="password"
                    placeholder="Leave blank to keep current"
                    value={editForm.passphrase}
                    onChange={(e) => setEditForm(prev => ({ ...prev, passphrase: e.target.value }))}
                    className="bg-[#0a192f] border-[#00b4d8]/20 text-white"
                  />
                </div>
              )}
              <div className="flex gap-2 pt-4">
                <Button
                  onClick={handleUpdateAccount}
                  disabled={!editForm.name.trim() || updateAccountMutation.isPending}
                  className="flex-1 bg-[#00b4d8] hover:bg-[#00b4d8]/80 text-white"
                >
                  Save Changes
                </Button>
                <Button
                  onClick={() => setEditingAccount(null)}
                  variant="outline"
                  className="border-[#00b4d8]/50 text-[#00b4d8] hover:bg-[#00b4d8]/10"
                >
                  Cancel
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}