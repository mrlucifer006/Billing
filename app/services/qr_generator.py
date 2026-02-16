import qrcode
import os
import uuid

class QRGenerator:
    def __init__(self, output_dir: str = "generated_qrs"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def generate_qr(self, data: str) -> str:
        """
        Generates a QR code for the given data and saves it to the output directory.
        Returns the absolute path of the generated image.
        """
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        
        # Create a unique filename
        filename = f"{uuid.uuid4()}.png"
        filepath = os.path.join(self.output_dir, filename)
        
        img.save(filepath)
        return os.path.abspath(filepath)
