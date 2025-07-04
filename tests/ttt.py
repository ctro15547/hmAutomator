class ctx:

    def __init__(self, **kwargs):
        self.kwargs = kwargs
    
    def __call__(self, **kwargs):
        self.kwargs.update(kwargs)
        return self

    def print_kwargs(self):
        print(self.kwargs)

    def print_ctx_id(self):
        print('ctx id', self.ctx_id)
    
    def check_print(self):
        print('check:', self.kwargs.get('text', 'No text provided'))


class phoneBase:

    def __init__(self, **kwargs):
        self.kwargs = kwargs
    
    def new_ctx(self):
        return ctx(**self.kwargs)

d = phoneBase(hello='world')
ctx1 = d.new_ctx()
ctx1(text='123').check_print()
ctx2 = d.new_ctx()
ctx2(text='456').check_print()
print('ctx1 id:', id(ctx1))
print('ctx2 id:', id(ctx2))