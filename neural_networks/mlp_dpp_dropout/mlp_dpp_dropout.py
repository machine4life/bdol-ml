import ConfigParser
import ast
import bdolpyutils as bdp
import dpp
import numpy as np
import shutil
import sys
import time
import uuid

def rectified_linear(X):
  return np.maximum(X, 0.0)

def d_rectified_linear(X):
  gZeroIdx = X>0
  return gZeroIdx*1

def softmax(X):
  # Use the log-sum-exp trick for numerical stability
  m = np.atleast_2d(np.amax(X, axis=1)).T
  y_exp = np.exp(X-m)

  s = np.atleast_2d(np.sum(y_exp, axis=1)).T

  return y_exp/s

def d_softmax(X):
  return X

def sigmoid(X):
  return 1.0/(1+np.exp(-X))

def d_sigmoid(X):
  return sigmoid(X)*(1-sigmoid(X))

def linear(X):
  return X


class Layer:
  def __init__(self, size, activation, d_activation):
    # TODO: make 0.01 a sigma parameter
    self.W = 0.01*np.random.randn(size[0], size[1])

    self.prev_Z = None
    self.activation = activation
    self.d_activation = d_activation
    self.z = np.zeros((size[0], size[1]))
    self.d = np.zeros((size[0], size[1]))
    self.a = 0

  def random_dropout(self, dropoutProb):
    self.prevZ[:, 0:-1] = self.prevZ[:, 0:-1]*np.random.binomial(1, (1-dropoutProb),
        (self.prevZ.shape[0], self.prevZ.shape[1]-1))

  def dpp_dropout(self, dropoutProb):
    if dropoutProb == 0:
      return

    W_n = self.W[0:-1, :]/np.linalg.norm(self.W[0:-1, :], axis=0)
    L = (W_n.dot(W_n.T))**2
    D, V = dpp.decompose_kernel(L)
    
    k = int(np.floor((1-dropoutProb)*self.W.shape[0]))
    J = dpp.sample_k(k, D, V)
    d_idx = np.zeros((self.W.shape[0]-1, 1))
    d_idx[J.astype(int)] = 1
  
    self.prevZ[:, 0:-1] = self.prevZ[:, 0:-1]*d_idx.T

  def compute_activation(self, X, doDropout=False, dropoutProb=0.5,
      testing=False, dropoutSeed=None):
    self.prevZ = np.copy(X)
    # I think you should drop out columns here?
    if doDropout:
      # We are not testing, so do dropout
      if not testing:
	self.dropoutFunction(dropoutProb)
        self.a = self.prevZ.dot(self.W)

      # We are testing, so we don't do dropout but we do scale the weights
      if testing:
        self.a = self.prevZ[:, 0:-1].dot(self.W[0:-1, :]*(1-dropoutProb))
        self.a += np.outer(self.prevZ[:, -1], self.W[-1, :])
    else:
      self.a = self.prevZ.dot(self.W)

    self.z = self.activation(self.a)
    self.d = self.d_activation(self.a)

    return self.z

class MLP:
  def __init__(self, layerSizes, activations, doDropout=False, dropoutType='nodropout', droputProb=0.5,
      dropoutInputProb=0.2, wLenLimit=15):
    self.doDropout = doDropout
    self.dropoutProb = dropoutProb
    self.dropoutInputProb = dropoutInputProb

    # Activations map - we need this to map from the strings in the *.ini file
    # to actual function names
    activationsMap = {'sigmoid': sigmoid,
                      'rectified_linear': rectified_linear,
                      'softmax': softmax}
    d_activationsMap = {'sigmoid': d_sigmoid,
                        'rectified_linear': d_rectified_linear,
                        'softmax': d_softmax}
    # Initialize each layer with the given parameters
    self.layers = []
    self.currentGrad = []
    for i in range(0, len(layerSizes)-1):
      size = [layerSizes[i]+1, layerSizes[i+1]]
      activation = activationsMap[activations[i]]
      d_activation = d_activationsMap[activations[i]]

      l = Layer(size, activation, d_activation)
      dropoutTypeMap = {'nodropout': None,
                        'dpp': l.dpp_dropout,
                        'random': l.random_dropout}

      l.dropoutFunction = dropoutTypeMap[dropoutType]
      self.layers.append(l)
      self.currentGrad.append(np.zeros(size))

  def forward_propagate(self, X, testing=False, dropoutSeeds=None):
    x_l = np.atleast_2d(X)
    for i in range(0, len(self.layers)):
      x_l = np.append(x_l, np.ones((x_l.shape[0], 1)), 1)
      if i==0: # We're at the input layer
        if dropoutSeeds:
          x_l = self.layers[i].compute_activation(x_l, doDropout,
              dropoutInputProb, testing, dropoutSeeds[i])
        else:
          x_l = self.layers[i].compute_activation(x_l, doDropout,
              dropoutInputProb, testing)
      else:
        if dropoutSeeds:
          x_l = self.layers[i].compute_activation(x_l, doDropout, dropoutProb,
              testing, dropoutSeeds[i])
        else:
          x_l = self.layers[i].compute_activation(x_l, doDropout, dropoutProb,
              testing)

    return x_l

  def xent_cost(self, X, Y, Yhat):
    E = np.array([0]).astype(np.float64)
    for i in range(0, Y.shape[0]):
      y = np.argmax(Y[i, :])
      E -= np.log(Yhat[i, y]).astype(np.float64)
      
    return E

  def check_gradient(self, X, Y, eta, momentum):
    eps = 1E-4
    dropoutSeeds = [232, 69, 75, 333]
    output = self.forward_propagate(X, dropoutSeeds=dropoutSeeds)
    W_grad = self.calculate_gradient(output, X, Y, eta, momentum)
    #print self.layers[0].prevZ[:, 710]
    #np.savetxt("prevZ", self.layers[0].prevZ)

    np.savetxt("X", X)
    np.savetxt("Y", Y)
    for i in range(0, len(self.layers)):
      np.savetxt("W_grad_"+str(i), W_grad[i])
      np.savetxt("W_"+str(i), self.layers[i].W)
    #sys.exit(0)
    
    W_initial = []
    for i in range(0, len(self.layers)):
      W_initial.append(np.copy(self.layers[i].W))

    for i in range(0, len(self.layers)):
      W = self.layers[i].W
      print " Checking layer",i
      layer_err = 0
      for j in range(0, W.shape[0]):
        for k in range(0, W.shape[1]):
          self.layers[i].W[j,k] += eps
          out_p = self.forward_propagate(X, dropoutSeeds=dropoutSeeds)
          E_p = self.xent_cost(X, Y, out_p)
          self.layers[i].W[j,k] = W_initial[i][j,k]
          self.layers[i].W[j,k] -= eps 
          out_m = self.forward_propagate(X, dropoutSeeds=dropoutSeeds)
          E_m = self.xent_cost(X, Y, out_m)
          self.layers[i].W[j,k] = W_initial[i][j,k]

          g_approx = (E_p-E_m)/(2*eps)
          g_calc = W_grad[i][j,k]
          err = abs(g_approx-g_calc)/(abs(g_approx)+abs(g_calc)+1E-10)
          layer_err += err
          if err>1E-3:
          #if g_approx == 0 and g_calc != 0:
            print " Gradient checking failed for ",i,j,k,g_approx,W_grad[i][j,k],E_p, E_m, err

        bdp.progBar(j, self.layers[i].W.shape[0])
      print layer_err

  def calculate_gradient(self, output, X, Y, eta, momentum):
    # First set up the gradients
    W_grad = []
    for i in range(0, len(self.layers)):
      W_grad.append( np.zeros(self.layers[i].W.shape) )

    e = output-Y

    # Backpropagate for each training example separately
    deltas = [e.T]
    for i in range(len(self.layers)-2, -1, -1):
      W = self.layers[i+1].W[0:-1, :]
      deltas.insert(0, np.multiply(self.layers[i].d.T, W.dot(deltas[0])))

    for i in range(0, len(self.layers)):
      W_grad[i] = (deltas[i].dot(self.layers[i].prevZ)).T

    return W_grad

  def backpropagate(self, output, X, Y, eta, momentum):
    W_grad = self.calculate_gradient(output, X, Y, eta, momentum)

    # Update the current gradient, and step in that direction
    for i in range(0, len(self.layers)):
      self.currentGrad[i] = momentum*self.currentGrad[i] - (1.0-momentum)*eta*W_grad[i]
      self.layers[i].W += self.currentGrad[i]
      #self.previousGrad[i] = np.copy(self.currentGrad[i])

      # Constrain the weights going to the hidden units if necessary
      #wLens = np.linalg.norm(self.layers[i].W, axis=0)**2
      #wLenCorrections = np.ones([1, self.layers[i].W.shape[1]])
      #wLenCorrections[0, np.where(wLens>wLenLimit)[0]] = wLens[wLens>wLenLimit]/wLenLimit
      #self.layers[i].W = self.layers[i].W/(np.sqrt(wLenCorrections))

  # Propagate forward through the network, record the training error, train the
  # weights with backpropagation
  def train(self, X, Y, eta, momentum):
    output = self.forward_propagate(X, testing=False)
    self.backpropagate(output, X, Y, eta, momentum)

  # Just pass the data forward through the network and return the predictions
  # for the given miniBatch
  def test(self, X):
    Yhat = np.zeros((X.shape[0], self.layers[-1].W.shape[1]))
    Yhat = self.forward_propagate(X, testing=True)
    return Yhat

def RMSE(Y, Yhat):
  rmse = 0
  for i in range(0, Y.shape[0]):
    y_i = np.where(Y[i, :])[0]
    rmse += (1-Yhat[i, y_i])**2
  return np.sqrt(1/float(Y.shape[0])*rmse)[0]

def numErrs(Y, Yhat):
  Y_idx = np.argmax(Y, axis=1)
  Yhat_idx = np.argmax(Yhat, axis=1)
  return np.sum(Y_idx != Yhat_idx)

if __name__ == "__main__":
  np.random.seed(1234)

  # Load the parameters for this network from the initialization file
  cfg = ConfigParser.ConfigParser()
  cfg.read(sys.argv[1])

  layerSizes = list(ast.literal_eval(cfg.get('net', 'layerSizes')))
  activations = cfg.get('net', 'activations').split(',')
  #doDropout = ast.literal_eval(cfg.get('net', 'doDropout'))
  dropoutType = cfg.get('net', 'dropoutType')
  if dropoutType == 'nodropout':
    doDropout = False
  else:
    doDropout = True
  dropoutProb = ast.literal_eval(cfg.get('net', 'dropoutProb'))
  dropoutInputProb = ast.literal_eval(cfg.get('net', 'dropoutInputProb'))
  wLenLimit = ast.literal_eval(cfg.get('net', 'wLenLimit'))
  momentumInitial = ast.literal_eval(cfg.get('net', 'momentumInitial'))
  momentumFinal = ast.literal_eval(cfg.get('net', 'momentumFinal'))
  momentumT = ast.literal_eval(cfg.get('net', 'momentumT'))

  mlp = MLP(layerSizes, activations, doDropout, dropoutType, dropoutProb, dropoutInputProb,
      wLenLimit)

  # Additionally load the experiment parameters
  digits = list(ast.literal_eval(cfg.get('experiment', 'digits')))
  mnistPath = cfg.get('experiment', 'mnistPath')
  numEpochs = ast.literal_eval(cfg.get('experiment', 'numEpochs'))
  minibatchSize = ast.literal_eval(cfg.get('experiment', 'minibatchSize'))
  learningRate = ast.literal_eval(cfg.get('experiment', 'learningRate'))
  rateDecay = ast.literal_eval(cfg.get('experiment', 'rateDecay'))
  checkGradient = ast.literal_eval(cfg.get('experiment', 'checkGradient'))

  # This option will continue the experiment for a certain number of epochs
  # after we have gotten 0 training errors
  numEpochsAfterOverfit = ast.literal_eval(cfg.get('experiment',
    'numEpochsAfterOverfit'))
  numEpochsRemaining = numEpochsAfterOverfit

  # Set up the program options
  debugMode = ast.literal_eval(cfg.get('program', 'debugMode'))
  logToFile = ast.literal_eval(cfg.get('program', 'logToFile'))
  logFileBaseName = cfg.get('program', 'logFileBaseName')
  if logToFile:
    dateStr = time.strftime('%Y-%m-%d_%H-%M')
    # Add a UUID so we can track this experiment
    uuidStr = uuid.uuid4()
    logFile = logFileBaseName+"_"+dateStr+"_"+str(uuidStr)+".txt"
    f = open(logFile, "w")
    f.write('Num. Errors Train,Num. Errors Test,learningRate,momentum,elapsedTime\n')
    # Also copy the params over for posterity
    paramsCopyStr = logFileBaseName+"_params_"+str(uuidStr)+".ini"
    shutil.copyfile(sys.argv[1], paramsCopyStr)

  # Load the corresponding data
  X_tr, Y_tr, X_te, Y_te = bdp.loadMNISTnp(mnistPath, digits=digits,
      asBitVector=True)

  print "Training for "+str(numEpochs)+" epochs:"
  p = momentumInitial
  for t in range(0, numEpochs):
    if t == 2:
      if checkGradient:
        print "Checking gradient..."
        mlp.check_gradient(X_tr[0:10, :], Y_tr[0:10, :], learningRate, 0)
        print " Gradient checking complete."

    startTime = time.time()

    for i in range(0, X_tr.shape[0], minibatchSize):
      mlp.train(X_tr[i:i+minibatchSize, :], Y_tr[i:i+minibatchSize],
          learningRate, p)


      if i%(1*minibatchSize)==0:
        bdp.progBar(i, X_tr.shape[0])
    bdp.progBar(X_tr.shape[0], X_tr.shape[0])

    elapsedTime = (time.time()-startTime)
    print " Epoch {0}, learning rate: {1:.4f}, momentum: {2:.4f} elapsed time: {3:.2f}s".format(t, learningRate, p, elapsedTime)

    # Decay the learning rate
    learningRate = learningRate*rateDecay

    # Update the momentum
    if t < momentumT:
      p = (1.0-float(t)/momentumT)*momentumInitial + (float(t)/momentumT)*momentumFinal
    else:
      p = momentumFinal

    # Calculate errors
    YhatTrain = mlp.test(X_tr)
    numErrsTrain = numErrs(Y_tr, YhatTrain)
    YhatTest = mlp.test(X_te)
    numErrsTest = numErrs(Y_te, YhatTest)

    errsStr = "Train errors: {0}\n".format(numErrsTrain)
    errsStr += "Test errors: {0}\n".format(numErrsTest)
    print errsStr

    logStr = "{0},{1},{2},{3},{4:.2f}\n".format(
                numErrsTrain, numErrsTest, learningRate, p, elapsedTime)
    if logToFile:
      f.write(logStr)
      f.flush()

    if numErrsTrain == 0 and numEpochsAfterOverfit > 0:
      print "No training errors. Continuing for {0} more epochs.".format(numEpochsRemaining) 
      numEpochsAfterOverfit -= 1
    elif numErrsTrain == 0 and numEpochsRemaining == 0:
      print "No training errors. Stopping."
      break
    elif numErrsTrain > 0:
      numEpochsRemaining = numEpochsAfterOverfit

  if logToFile:
    f.close()
